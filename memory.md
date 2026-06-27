# Session Memory — MLOps E2E Evaluation Pipeline

> Working/context log so the assistant can fully restore state after a reset or
> compaction. **Update cadence: every ~5 interactions** (and at any major
> milestone). Last updated: 2026-06-27 — ALL 4 PHASES COMPLETE & VERIFIED ON VM.

## POST-COMPLETION POLISH (2026-06-27)
- VM was DESTROYED (so the good uv.lock with mlflow/boto3 is gone; committed
  uv.lock is STALE — lacks mlflow/boto3). FIX: Dockerfile now uses `uv sync`
  (NOT --locked) so the eval image builds regardless of lock state. To re-pin:
  `uv lock` on a Python>=3.12 host, commit, switch back to --locked. (Sandbox
  only has py3.10 + can't download 3.12, so couldn't regenerate here.)
- README rewritten as a reproduction guide (overview + repro steps mirroring
  SETUP.md + links to REPORT.md and docs/ASSIGNMENT.md). Original lecturer
  assignment text preserved verbatim in docs/ASSIGNMENT.md.

## STATUS: COMPLETE
Full DockerOperator run green end-to-end; artifacts uploaded to local MinIO S3;
manifest has remote_artifact_uri; MLflow shows multiple runs (comparison view).
All 3 screenshots captured in screenshots/ (airflow_dag, mlflow_runs,
object_storage_artifacts). All rubric deliverables present. Remaining: user
commits/pushes final changes + screenshots from Mac. Optional polish only.

## Standing instructions from the user

1. **Update this `memory.md` every ~5 interactions** (and at milestones).
2. **Keep `docs/SETUP.md` complete** — every step we do (setup, run, debug, each
   new phase) must be documented there so the runbook is always current.

---

## 1. What the assignment is

Nebius Academy "AI Performance Engineering" course, MLOps module, lecture #6
("End-to-end ML pipeline"). Home assignment by Simon Karasik.

**Goal:** turn ad-hoc shell scripts that (a) run a coding agent
(`mini-swe-agent`) on SWE-bench tasks and (b) evaluate the produced patches
with the SWE-bench harness, into a **configurable, reproducible Airflow
pipeline** with structured artifacts + MLflow tracking. Production-style adds
DockerOperator, docker-compose (Airflow+MLflow), and S3 upload.

Core workflow: `run-agent -> run-evaluation -> save-artifacts -> log-metrics`.

**Grading weights:** Configurable DAG 35%, artifact structure/reproducibility
20%, MLflow 15%, execution isolation (Docker) 10%, Docker Compose 10%, REPORT.md
10%. Philosophy: provenance/reproducibility > one lucky metric.

**Target scope (user decision):** FULL production-style (all of the above).

## 2. Key decisions made

- **Scope:** full production-style; build **phase by phase**, validating each.
- **Object storage:** Nebius S3-compatible (not AWS).
- **Git workflow:** user pushed the repo to THEIR GitHub account; cloned to VM
  over **HTTPS** (public repo, no SSH/agent-forwarding needed). `origin` = their
  repo, `upstream` = lecturer's `minotru/mlops-assignment-e2e-ml-pipeline`.
- **Reference repos location:** `mini-swe-agent/` and `SWE-bench/` are cloned
  **ALONGSIDE** the project (siblings in the parent dir), NOT inside it. The
  pipeline resolves the agent config from the sibling automatically
  (`pipeline/config.py::_resolve_agent_config`, override via `MSWEA_REPOS_DIR`).
- **MLflow:** MLflow 3.x deprecated the `./mlruns` file store, so the helper
  falls back to a **SQLite** store (`sqlite:///mlflow.db`) when no tracking
  server is set; the compose stack (Phase 3) will run a real MLflow server.

## 3. Environment / infra facts

- **VM:** user-created Nebius CPU VM (target 8 vCPU / 32 GB / public IP). Linux
  user `manuel`, hostname like `computeinstance-...`. Repo path on VM:
  `~/mlops-e2e-pipeline`.
- **Inference:** `NEBIUS_API_KEY` in `.env` (Nebius Token Factory). No GPU needed.
- **Default model:** `nebius/moonshotai/Kimi-K2.6`.
- **Tooling on VM:** uv + Docker (installed via `scripts/bootstrap-vm.sh`).

## 4. CRITICAL constraints for the assistant

- **Git does NOT work from the assistant sandbox** — the mounted filesystem
  blocks git's unlink/rename, leaving stale `.git/index.lock`. So: the assistant
  edits files (which appear in the user's working tree), but **the USER runs all
  git commit/push from their Mac**, then `git pull` on the VM.
- Local Mac repo path:
  `/Users/emanuel/cursor projects/assignment 11 - E2E ML Pipeline/mlops-assignment-e2e-ml-pipeline`
- Sandbox path (bash):
  `/sessions/.../mnt/assignment 11 - E2E ML Pipeline/mlops-assignment-e2e-ml-pipeline`
- Standard handoff after edits: **Mac** `git add -A && git commit -m "..." && git push`
  → **VM** `git pull` (+ `uv sync` if deps changed).

## 5. Progress / phase status

- **Phase 1 ✅** Configurable DAG + pipeline helpers + structured runs/ + sample run.
- **Phase 2 ✅** MLflow tracking (params, metrics, artifacts, manifest cross-ref).
- **Phase 2.1 ✅** Put project venv on PATH for DAG subprocesses (standalone fix).
- **Phase 3 ◐ IN PROGRESS**
  - 3a DONE (not yet run on VM): `docker-compose.yaml` (LocalExecutor: postgres +
    mlflow server + airflow-init/apiserver/scheduler/dag-processor),
    `docker/Dockerfile.airflow` (airflow + providers-docker + providers-fab +
    mlflow + boto3), `docker/Dockerfile.mlflow` (python + mlflow + psycopg2 +
    boto3), `docker/initdb/01-create-mlflow-db.sql`, `.env.example` compose vars,
    SETUP.md Section E. Docker socket mounted; group_add DOCKER_GID. MLflow server
    backend = postgres `mlflow` db, artifacts in a volume. YAML lints OK.
    NEXT for user: fill .env compose vars, `docker build -t mlops-eval:latest .`,
    `docker compose build && up -d`, verify UIs (8080 Airflow, 5000 MLflow).
  - 3a HEALTHY on VM: all 7 services up, Airflow :8080 + MLflow :5000 accessible.
    (Fixes that got there: minimal airflow image; init uses image entrypoint +
    _AIRFLOW_DB_MIGRATE; init runs as root and chowns logs/runs dirs.)
  - 3b DONE (not yet run on VM): `dags/evaluate_agent_docker.py` —
    prepare_run (python @task) -> run_agent/run_eval/summarize_and_log (all
    DockerOperator on the eval image). DooD approach: mount project +
    sibling mini-swe-agent at IDENTICAL host paths (HOST_PROJECT_DIR/
    HOST_PARENT_DIR) so paths match in/out of container; mount docker.sock;
    network_mode=COMPOSE_NETWORK so summarize reaches mlflow:5000. run_id flows
    via XCom Jinja templates. summarize runs `python -m pipeline.summarize` in the
    eval image (has mlflow/boto3 via uv) -> keeps airflow image clean.
    Refactored runner.py: `_collect_reports`->public `collect_reports`, added
    `collect_preds`; both reused by pipeline/summarize.py. Added COMPOSE_NETWORK
    to compose env + .env.example. py_compile + helper smoke test pass.
    NEXT for user: build eval image, ensure .env has HOST_*/EVAL_IMAGE/
    COMPOSE_NETWORK, `docker compose up -d`, trigger `evaluate_agent_docker` with
    {"subset":"verified","split":"test","workers":1,"task_slice":"0:1"}.
    WATCH-OUTS: eval image build needs uv.lock to include mlflow/boto3 (it built
    on VM already); auto_remove="success" + mount_tmp_dir=False on operators;
    DOCKER_GID must match host for in-container socket access.
  - Compose targets Airflow 3.x; AIRFLOW_IMAGE_NAME must match user's standalone
    version. Could need version tweaks on first bring-up (untested in sandbox).
  - RECONCILED against official Airflow compose (user fetched it; their version =
    **3.2.2**). Kept LocalExecutor (dropped Celery/redis/worker/flower) but adopted
    the critical 3.x bits: AIRFLOW__API_AUTH__JWT_SECRET (shared across services,
    via AIRFLOW_JWT_SECRET in .env), AIRFLOW__CORE__EXECUTION_API_SERVER_URL=
    http://airflow-apiserver:8080/execution/, AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK,
    correct healthchecks (apiserver /api/v2/monitor/health, scheduler :8974/health,
    dag-processor & triggerer `airflow jobs check`), added airflow-triggerer.
    Default image now apache/airflow:3.2.2.
  - BRING-UP BUG #1 (REAL cause, fixed): airflow-init failed with "No module
    named 'airflow'" because it OVERRODE `entrypoint: /bin/bash` and called bare
    `airflow db migrate`, which bypasses the image entrypoint that sets up
    Airflow's Python env. (Earlier mlflow-clobber theory was WRONG -- the
    scheduler, which uses the default entrypoint, imported airflow fine even with
    mlflow installed; only init failed.) FIX: airflow-init now uses the image's
    default entrypoint with `command: version` + `_AIRFLOW_DB_MIGRATE=true` +
    `_AIRFLOW_WWW_USER_CREATE=true` (the documented mechanism). Only a compose
    change -> `docker compose down && up -d` (no rebuild needed).
  - SIDE EFFECT: Dockerfile.airflow was slimmed to providers-docker only (mlflow
    removed). So for 3b the summarize/MLflow step must run in the EVAL image
    (DockerOperator), not as an in-Airflow Python task -- OR re-add mlflow+boto3
    to Dockerfile.airflow (it imported fine alongside airflow). DECIDE in 3b.
- **Phase 3 ✅ COMPLETE (2026-06-27):** full end-to-end DockerOperator run on the
  VM — all 4 tasks green, run logged to the compose MLflow server (experiment
  swe-bench-agent-eval, resolve_rate 1.0). Fixes during 3b bring-up:
  EvalDockerOperator with empty template_ext (the `.sh` command arg was being
  loaded as a Jinja template file); MLflow server needs `--allowed-hosts '*'
  --cors-allowed-origins '*'` (3.x security middleware rejected Host: mlflow:5000
  with 403 "Invalid Host header"). DooD mounts + compose network + XCom templating
  all working.
- **Phase 4 ◐ IN PROGRESS** (code done, not yet run with real S3 on VM):
  - `pipeline/storage.py`: upload_run_dir + upload_file (boto3, Nebius S3-compat,
    OPTIONAL — skips if S3 env unset / placeholder XXX). Endpoint
    https://storage.eu-north1.nebius.cloud, region eu-north1.
  - `pipeline/summarize.py`: now has shared `summarize_run()` (collect_preds +
    collect_reports + metrics + S3 upload + mlflow(with s3 uri) + manifest +
    re-upload manifest). BOTH DAGs call it (evaluate_agent.py refactored to use it;
    docker DAG runs `python -m pipeline.summarize`).
  - docker DAG summarize operator + compose airflow-common-env now forward
    S3_*/AWS_* vars. .env.example already had the S3 block.
  - REPORT.md written (architecture, params table, artifact layout, MLflow,
    Docker isolation, S3, rerun, one completed run). SETUP.md §G = S3 config
    (Nebius aws-configure -> our env mapping). .gitignore: mlruns/, *.db.
  - Smoke-tested summarize_run on sample-run (S3 skipped -> None, mlflow logged).
  - S3 TARGET DECISION: lecturer did NOT grant IAM perms to create Nebius S3
    access keys, and Nebius S3 can't be used without creds. So compose now ships
    a local **MinIO** service (+ minio-init bucket creator) as the default S3
    target. minio root creds == AWS_ACCESS_KEY_ID/SECRET; console on :9001;
    bucket = S3_BUCKET. storage.py uses path-style addressing (Config) for
    MinIO/Nebius compat. .env.example has Option A (MinIO, default) + Option B
    (Nebius, commented). SETUP §G documents both. Switching to Nebius = .env only.
  - NEXT for user: set MinIO .env block (secret >=8 chars), `docker compose up -d`,
    trigger evaluate_agent_docker, verify remote_artifact_uri in manifest + S3
    URI in MLflow + objects in MinIO console (:9001); capture 3 screenshots into
    screenshots/ (airflow_dag, mlflow_runs, object_storage_artifacts).
  + 3 screenshots (Airflow DAG, MLflow runs, object storage).

**MILESTONE (2026-06-27):** First full end-to-end run on the VM — all 4 tasks
GREEN in standalone Airflow with `{"subset":"verified","split":"test",
"workers":1,"task_slice":"0:1"}`. run_id `20260627-144612__nebius__moonshotai__Kimi-K2.6`,
resolve_rate 1.0 (1/1 resolved), MLflow run `ee9f73e4...` logged to local
`sqlite:///mlflow.db` + `mlruns/` artifacts. Phases 1–2 validated on real infra.

Fixes that got us there (all committed): removed unsupported `--cost-limit` from
batch run-agent.sh; added `--with mlflow --with boto3` to run-airflow-standalone.sh
(Python tasks import in Airflow's env); venv-on-PATH for subprocess tasks.

**NEXT:** Phase 3 — DockerOperator + docker-compose (Airflow + MLflow + postgres).

## 6. Files created/changed by the assistant

- `dags/evaluate_agent.py` — 4-task DAG (`prepare_run`→`run_agent`→`run_eval`→
  `summarize_and_log`), Airflow Params: split, subset, workers, model, task_slice,
  run_id, cost_limit. Retries=1.
- `pipeline/__init__.py`, `config.py`, `layout.py`, `runner.py`, `metrics.py`,
  `manifest.py`, `mlflow_utils.py` — helper package (thin DAG delegates here).
- `scripts/run-agent.sh`, `scripts/run-eval.sh` — env-parameterized (reused by
  DockerOperator later). `scripts/bootstrap-vm.sh` — VM setup.
- `scripts/mini-swe-bench-batch.sh` — updated config path to `../mini-swe-agent/...`.
- `docs/SETUP.md` — push-to-account + VM bootstrap runbook.
- `.env.example` — Nebius key, MLflow, MSWEA_REPOS_DIR, Nebius S3 placeholders.
- `pyproject.toml` — added `mlflow`, `boto3`.
- `runs/sample-run/` — validated reproducible sample tree (committed; rest of
  `runs/*` is gitignored).
- `.gitignore` — ignores `.DS_Store`, reference repos, `runs/*` except sample-run.

## 7. Data formats (from sample/)

- `preds.json`: `{instance_id: {model_name_or_path, instance_id, model_patch}}`.
- harness summary json `<model_slug>.<run_id>.json`: total/submitted/completed/
  resolved/unresolved/empty_patch/error counts + id lists. `model_slug` =
  `model.replace('/','__')`.
- per-instance `report.json` keyed by instance_id with `resolved` bool +
  `tests_status`.
- trajectories: `runs/<id>/run-agent/trajectories/<instance>/<instance>.traj.json`
  (keys: info, messages, trajectory_format, instance_id) + `preds.json` +
  `exit_statuses_*.yaml` + `minisweagent.log`.

## 8. Run directory layout (canonical)

```
runs/<run-id>/
  config.json
  run-agent/{preds.json, trajectories/, run-agent.log}
  run-eval/{logs/, reports/{summary.json, <instance>.report.json}, run-eval.log}
  metrics.json
  manifest.json   # points to artifacts + embeds mlflow run id/uri
```

## 9. Validation done (in sandbox, against sample data)

- Helper chain reconstructs the run tree correctly; metrics parse = 1/3 resolved,
  resolve_rate 0.33.
- MLflow logging verified end-to-end against a sqlite store: 9 params, 8 metrics,
  4 artifacts logged + queryable; manifest cross-references the mlflow run.
- All python compiles; both shell scripts pass `bash -n`.

## 10. Open items / watch-outs

- `--cost-limit` is NOT supported by the batch `mini-extra swebench` subcommand
  (only `swebench-single`). RESOLVED: removed the flag from run-agent.sh; batch
  cost/step limits come from the `--config` yaml. cost_limit param is kept for
  provenance (config.json + MLflow). TODO (optional): wire cost_limit by
  templating a derived config yaml if we want it to actually take effect in batch.
- Phase 3: SWE-bench eval in a container requires mounting `/var/run/docker.sock`.
- Airflow needs `NEBIUS_API_KEY` in its env: user runs `set -a; source .env; set +a`
  before `run-airflow-standalone.sh`.
- **Two execution envs (important):** Python `@task`s (prepare_run,
  summarize_and_log) run inside the Airflow uv-tool env; subprocess tasks
  (run_agent, run_eval) shell into the project `.venv`. RESOLVED a
  `No module named 'mlflow'` failure by adding `--with mlflow --with boto3` to
  the `uv tool run apache-airflow standalone` line in run-airflow-standalone.sh.
  After editing that script, restart Airflow + Clear the failed task. Phase 3
  (DockerOperator) removes this env split.
