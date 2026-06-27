# Evaluation pipeline for coding-agent experiments — Report

Turns the ad-hoc `scripts/` into a configurable, reproducible, observable Airflow
pipeline that runs `mini-swe-agent` on a SWE-bench subset and evaluates the
produced patches, with structured artifacts, MLflow tracking, Docker isolation,
and Object Storage.

## Architecture

The pipeline implements `run-agent -> run-evaluation -> save-artifacts -> log-metrics`
as a four-task Airflow DAG:

```
prepare_run -> run_agent -> run_eval -> summarize_and_log
```

- **prepare_run** reads the Airflow params, resolves a full run config (mapping
  `subset` to the SWE-bench `dataset_name`, recording the git SHA), and creates
  `runs/<run-id>/config.json`.
- **run_agent** runs `mini-swe-agent` over the selected subset/slice and writes
  trajectories + `preds.json` into `runs/<run-id>/run-agent/`.
- **run_eval** runs the SWE-bench harness on `preds.json` and writes logs +
  reports into `runs/<run-id>/run-eval/`.
- **summarize_and_log** parses the reports into `metrics.json`, uploads the run
  folder to Object Storage (optional), logs params/metrics/artifact-refs to
  MLflow, and writes `manifest.json`.

There are **two DAGs sharing one `pipeline/` helper package**:

| DAG | Execution | Use |
|---|---|---|
| `evaluate_agent` | local subprocess (`scripts/*.sh` in the project venv) | standalone Airflow; fast to iterate/debug |
| `evaluate_agent_docker` | `DockerOperator` (agent/eval/summarize in the eval image) | production-style; runs on the Docker Compose stack |

The Compose deployment runs **Airflow (LocalExecutor) + MLflow server + Postgres**.
The agent and evaluation steps need Docker (SWE-bench spawns a container per task),
so the Docker socket is mounted into the eval containers (docker-out-of-docker).

```
docker-compose: postgres + mlflow(server) + airflow(apiserver/scheduler/dag-processor/triggerer/init)
        │
        ▼  evaluate_agent_docker
   prepare_run ─▶ run_agent ─▶ run_eval ─▶ summarize_and_log
   (python)      (docker)     (docker)     (docker)
                    │             │             │
               trajectories   eval logs/    metrics.json + manifest.json
               + preds.json    reports       → MLflow + S3
```

## How to trigger a run

**Standalone** (`evaluate_agent`): `bash run-airflow-standalone.sh`, open
http://localhost:8080, trigger the DAG.

**Compose** (`evaluate_agent_docker`): `docker compose up -d`, open
http://localhost:8080, trigger the DAG. MLflow UI at http://localhost:5000.

Both are configured from **Airflow Params** (no hard-coded experiment values):

| Param | Required | Default | Meaning |
|---|---|---|---|
| `split` | yes | `test` | dataset split |
| `subset` | yes | `verified` | SWE-bench subset (`verified`/`lite`/`full`/`multimodal`) |
| `workers` | yes | `5` | parallel workers |
| `model` | no | `nebius/moonshotai/Kimi-K2.6` | LiteLLM model id |
| `task_slice` | no | `0:3` | instance slice |
| `run_id` | no | auto `YYYYMMDD-HHMMSS__<model>` | output folder name |
| `cost_limit` | no | `0` | per-instance cost (provenance; batch limits come from the agent config) |

Example trigger config:

```json
{"subset": "verified", "split": "test", "workers": 1, "task_slice": "0:1"}
```

## Artifact layout

Every run produces a self-contained, reproducible tree:

```
runs/<run-id>/
  config.json              # resolved config + git sha (provenance)
  run-agent/
    preds.json             # SWE-bench predictions
    trajectories/          # per-instance agent transcripts + logs
  run-eval/
    logs/                  # SWE-bench harness logs (per-instance)
    reports/               # summary.json + <instance>.report.json
  metrics.json             # parsed results
  manifest.json            # index: artifact paths + MLflow run id + remote (S3) URI
```

Handing someone `runs/<run-id>/` is enough to reconstruct the whole run:
inputs, configuration, trajectories, predictions, evaluation logs, metrics.
`manifest.json` cross-references the MLflow run and the S3 location.

A committed example lives in [`runs/sample-run/`](runs/sample-run/).

## MLflow tracking

`summarize_and_log` logs one MLflow run per pipeline run to the experiment
`swe-bench-agent-eval`: all params, the metrics (`resolved_instances`,
`unresolved_instances`, `resolve_rate`, ...), the run id, the small artifacts
(`config.json`, `metrics.json`, `manifest.json`, `preds.json`), and tags for the
local artifact dir and the remote (S3) URI. Multiple runs are then comparable in
the MLflow UI by params/metrics.

- Standalone: logs to `sqlite:///mlflow.db` (3.x deprecated the bare file store).
- Compose: logs to the MLflow **server** (`http://mlflow:5000`, Postgres-backed).

See `screenshots/mlflow_runs.png`.

## Execution isolation (Docker)

`evaluate_agent_docker` runs the agent, evaluation, and summarize steps inside
the **eval image** (built from the root `Dockerfile`: uv + the project venv with
`mini-swe-agent`/`swebench`/`mlflow`). The Airflow image stays minimal
(`apache-airflow-providers-docker` only). DockerOperator bind-mounts the project
and the sibling `mini-swe-agent` at their identical host paths so absolute paths
match in and out of the container, and mounts the Docker socket so the eval steps
can spawn SWE-bench's per-task containers.

See `screenshots/airflow_dag.png`.

## Object Storage (S3-compatible)

When the S3 env vars are set, `summarize_and_log` mirrors the whole
`runs/<run-id>/` folder to `s3://<bucket>/<prefix>/<run-id>/`, logs that URI to
MLflow, and records it in `manifest.json` (`remote_artifact_uri`). If S3 is not
configured the step is skipped and the local run folder is still complete.

The uploader (`pipeline/storage.py`, boto3, path-style addressing) is endpoint-
agnostic, so it targets **any** S3-compatible store. The compose stack ships a
local **MinIO** service (+ a `minio-init` that creates the bucket) as the default
target — Nebius Object Storage requires service-account access keys that need IAM
permissions to mint, so MinIO provides the same S3 API for a self-contained demo.
Switching to Nebius is purely an `.env` change (endpoint + bucket + keys).

See `screenshots/object_storage_artifacts.png`.

## Reproduce / rerun

```bash
# Compose stack (production-style)
docker build -t mlops-eval:latest .
docker compose build && docker compose up -d
# trigger evaluate_agent_docker from the UI with a run config (above)

# Rerun a specific run id: pass {"run_id": "<id>", ...} in the trigger config.
# Reconstruct a past run: read runs/<run-id>/manifest.json, or pull
#   s3://<bucket>/<prefix>/<run-id>/ from Object Storage.
```

Full setup (VM provisioning, repos, compose bring-up, troubleshooting) is in
[`docs/SETUP.md`](docs/SETUP.md).

## One completed run

`task_slice 0:1` on SWE-bench Verified with `nebius/moonshotai/Kimi-K2.6`:
1 submitted, 1 resolved, **resolve_rate 1.0**, logged to MLflow and written to
`runs/<run-id>/`. (See `runs/sample-run/` for the artifact shape.)
