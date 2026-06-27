# Evaluation pipeline for coding-agent experiments

A configurable, reproducible, observable **Airflow** pipeline that runs
[`mini-swe-agent`](https://github.com/SWE-agent/mini-swe-agent) on a
[SWE-bench](https://www.swebench.com/) subset and evaluates the produced patches,
with a structured artifact footprint, **MLflow** tracking, **Docker** isolation,
**Docker Compose** deployment, and **S3** object storage.

> **Context.** This repo is my solution to the Nebius Academy *AI Performance
> Engineering* course, MLOps module, lecture #6 ("End-to-end ML pipeline"),
> by Simon Karasik. The original assignment brief is preserved verbatim in
> [`docs/ASSIGNMENT.md`](docs/ASSIGNMENT.md).
>
> - **What was built and why → [`REPORT.md`](REPORT.md)** (architecture, results, design decisions)
> - **Full step-by-step runbook → [`docs/SETUP.md`](docs/SETUP.md)** (VM, compose, troubleshooting)
> - This README is the **condensed reproduction guide** — enough to recreate the
>   whole setup from scratch, pointing to `docs/SETUP.md` for exhaustive detail.

## What it does

The pipeline implements `run-agent -> run-evaluation -> save-artifacts -> log-metrics`
as a four-task Airflow DAG:

```
prepare_run -> run_agent -> run_eval -> summarize_and_log
```

It takes a research config (model, dataset subset, slice, workers), runs the
coding agent on those SWE-bench tasks, evaluates the patches with the real
SWE-bench harness, writes a self-contained `runs/<run-id>/` folder, logs
params/metrics/artifact-refs to MLflow, and (optionally) uploads the run to S3.

There are **two DAGs sharing one `pipeline/` package**:

| DAG | Execution | When to use |
|---|---|---|
| `evaluate_agent` | local subprocess (project venv) | standalone Airflow; quick iteration |
| `evaluate_agent_docker` | `DockerOperator` (eval image) | the Compose deployment; production-style |

## Architecture

```
docker-compose: postgres + mlflow(server) + minio(S3) + airflow(LocalExecutor)
        │
        ▼  evaluate_agent_docker
   prepare_run ─▶ run_agent ─▶ run_eval ─▶ summarize_and_log
   (python)      (docker)     (docker)     (docker)
                    │             │             │
               trajectories   eval logs/    metrics.json + manifest.json
               + preds.json    reports       → MLflow + S3 (MinIO/Nebius)
```

Three layers cooperate: **Airflow** orchestrates; the **`runs/<run-id>/`** folder
(mirrored to **S3**) is the durable, reproducible record; **MLflow** is the
searchable index/dashboard over runs. See [`REPORT.md`](REPORT.md) for detail.

## Repository layout

| Path | What |
|---|---|
| `dags/evaluate_agent.py` | standalone (subprocess) DAG |
| `dags/evaluate_agent_docker.py` | production DAG (DockerOperator) |
| `pipeline/` | helper package: config, layout, runner, metrics, mlflow, storage, summarize, manifest |
| `scripts/run-agent.sh`, `run-eval.sh` | env-parameterized agent/eval scripts (shared by both execution modes) |
| `scripts/bootstrap-vm.sh` | one-shot VM setup (uv + Docker + clone reference repos) |
| `Dockerfile` | eval image (agent + swebench + mlflow via uv) |
| `docker/Dockerfile.airflow`, `Dockerfile.mlflow` | compose images |
| `docker-compose.yaml` | Airflow + MLflow + Postgres + MinIO |
| `runs/sample-run/` | committed example of the run-folder layout |
| `screenshots/` | Airflow DAG, MLflow runs, object storage |
| `docs/SETUP.md` | detailed runbook · `docs/ASSIGNMENT.md` original brief · `REPORT.md` writeup |

## Reproduce from scratch

Full detail and troubleshooting are in [`docs/SETUP.md`](docs/SETUP.md) (sections
referenced below). The condensed path:

### 0. Prerequisites

- A CPU VM with **8 vCPU / 32 GB RAM / public IP** (e.g. Nebius). No GPU needed —
  inference is a managed API.
- A **`NEBIUS_API_KEY`** (Nebius Token Factory) for the agent's model.
- Docker + uv on the VM (the bootstrap script installs them).

### 1. Get the code onto the VM

```bash
git clone <this-repo-url>
cd <repo>
bash scripts/bootstrap-vm.sh      # installs uv + Docker, clones mini-swe-agent
                                  # and SWE-bench alongside, runs uv sync
```
The two upstream repos are cloned **as siblings** of this project (see
`docs/SETUP.md` "Where the two reference repos live"). Then `newgrp docker` /
reconnect so Docker works without sudo (SETUP "Use Docker without sudo").

### 2. Configure `.env`

```bash
cp .env.example .env
# set NEBIUS_API_KEY, and the compose vars: AIRFLOW_UID, DOCKER_GID,
# HOST_PROJECT_DIR, HOST_PARENT_DIR, AIRFLOW_JWT_SECRET, and the S3/MinIO block.
```
See `docs/SETUP.md` §E2 (compose vars) and §G (object storage).

### 3. Run it — two options

**Quick (standalone Airflow):**
```bash
set -a; source .env; set +a
bash run-airflow-standalone.sh        # UI on :8080, trigger `evaluate_agent`
```

**Production (Docker Compose — Airflow + MLflow + Postgres + MinIO):**
```bash
docker build -t mlops-eval:latest .   # eval image
docker compose build && docker compose up -d
# Airflow UI :8080 (admin/admin) · MLflow :5000 · MinIO console :9001
# trigger `evaluate_agent_docker`
```

### 4. Trigger a run

From the Airflow UI, "Trigger DAG w/ config":
```json
{"subset": "verified", "split": "test", "workers": 1, "task_slice": "0:1"}
```

### 5. Where the results go

- `runs/<run-id>/` — the full reproducible tree (see below)
- MLflow (`swe-bench-agent-eval` experiment) — params, metrics, artifact refs
- S3 (`s3://<bucket>/runs/<run-id>/`) — when configured (MinIO by default)

## Pipeline parameters

Configured entirely from Airflow Params — no hard-coded experiment values.

| Param | Required | Default | Meaning |
|---|---|---|---|
| `split` | yes | `test` | dataset split |
| `subset` | yes | `verified` | SWE-bench subset (`verified`/`lite`/`full`/`multimodal`) |
| `workers` | yes | `5` | parallel workers |
| `model` | no | `nebius/moonshotai/Kimi-K2.6` | LiteLLM model id |
| `task_slice` | no | `0:3` | instance slice |
| `run_id` | no | auto | output folder name (pass to pin / rerun) |
| `cost_limit` | no | `0` | per-instance cost (provenance) |

## Artifact layout

```
runs/<run-id>/
  config.json              # resolved config + git sha
  run-agent/
    preds.json             # SWE-bench predictions
    trajectories/          # per-instance agent transcripts
  run-eval/
    logs/                  # SWE-bench harness logs
    reports/               # summary.json + <instance>.report.json
  metrics.json             # parsed results
  manifest.json            # index: paths + MLflow run id + remote (S3) URI
```

Handing someone `runs/<run-id>/` is enough to reconstruct the whole run. A
committed example lives in [`runs/sample-run/`](runs/sample-run/).

## Results

A completed run, the MLflow comparison view, and the object-storage upload are
shown in [`screenshots/`](screenshots/) and discussed in [`REPORT.md`](REPORT.md).

## Notes

- The eval image build runs `uv sync` (resolving deps from `pyproject.toml`), so
  it builds even if `uv.lock` lags. For strict pinning, run `uv lock` on a host
  with Python ≥ 3.12, commit the refreshed `uv.lock`, and switch the `Dockerfile`
  back to `uv sync --locked`.
- Object storage is optional and S3-compatible: the default is a local **MinIO**
  service in the compose stack; switching to **Nebius Object Storage** is a pure
  `.env` change (endpoint + bucket + service-account access keys). See
  `docs/SETUP.md` §G.
