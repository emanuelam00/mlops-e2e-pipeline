# Session Memory — MLOps E2E Evaluation Pipeline

> Working/context log so the assistant can fully restore state after a reset or
> compaction. **Update cadence: every ~5 interactions** (and at any major
> milestone). Last updated: 2026-06-27, after adding run steps to SETUP.md.

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
- **Phase 3 ⬜ (NEXT)** DockerOperator + `docker-compose.yaml` (Airflow + MLflow +
  postgres). SWE-bench eval needs the Docker socket mounted (docker-out-of-docker).
- **Phase 4 ⬜** Nebius S3 upload of `runs/<run-id>/` + log URI to MLflow + REPORT.md
  + 3 screenshots (Airflow DAG, MLflow runs, object storage).

**Immediate next action (in flight):** user is doing an end-to-end validation run
in **standalone Airflow** with a tiny config
`{"subset":"verified","split":"test","workers":1,"task_slice":"0:1"}` to confirm
Phases 1–2 work on the VM before Dockerizing. Waiting on the result / any task logs.

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
