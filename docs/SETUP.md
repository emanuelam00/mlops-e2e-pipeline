# Setup runbook: your account + your VM

This is the practical, copy-paste sequence to (A) push this repo to **your**
GitHub account over SSH, and (B) pull it onto the VM you already created and
install everything (including the two upstream reference repos).

Placeholders to replace:

| Placeholder | Meaning |
|---|---|
| `<YOUR_GH_USERNAME>` | your GitHub username |
| `<REPO_NAME>` | the new repo name, e.g. `mlops-assignment-e2e-ml-pipeline` |
| `<VM_USER>` | your Linux user on the VM |
| `<VM_IP>` | the VM's public IP |

---

## A. Push to your GitHub account (run on your Mac)

> Run these in **your Mac terminal**, in this project folder. (Git can't be
> driven from the assistant sandbox — the mounted filesystem blocks git's
> internal file operations — so committing/pushing happens here.)

**A0. Clear the stale lock** left by the sandbox's commit attempt, if present:

```bash
cd "/Users/emanuel/cursor projects/assignment 11 - E2E ML Pipeline/mlops-assignment-e2e-ml-pipeline"
rm -f .git/index.lock
```

**A1. Commit the Phase 1 work:**

```bash
git add -A
git status            # sanity check: pipeline/, dags/evaluate_agent.py, scripts/*.sh, runs/sample-run/
git commit -m "Phase 1: configurable evaluate_agent DAG + pipeline helpers + sample run"
```

**A2. Create an empty repo on github.com** (UI): New repository →
name `<REPO_NAME>` → **do NOT** add README/.gitignore/license (keep it empty) →
Create.

**A3. Keep the lecturer's repo as `upstream`, point `origin` at yours, push:**

```bash
git remote rename origin upstream
git remote add origin git@github.com:<YOUR_GH_USERNAME>/<REPO_NAME>.git
git push -u origin main
```

Verify with `git remote -v` — `origin` = yours, `upstream` = lecturer's.
(Keeping `upstream` lets you pull any future fixes the lecturer pushes.)

> Uses SSH, so your GitHub SSH key must be loaded: `ssh-add -l` should list it;
> test with `ssh -T git@github.com`.

---

## B. SSH into the VM with agent forwarding

Agent forwarding lets the VM use **your** GitHub SSH key to clone, without
copying any private key onto the VM. Add this to `~/.ssh/config` on your Mac:

```sshconfig
Host academy-vm
  HostName <VM_IP>
  User <VM_USER>
  ForwardAgent yes
```

Then:

```bash
ssh academy-vm
# on the VM, confirm the forwarded key works against GitHub:
ssh -T git@github.com      # should greet you by your GitHub username
```

---

## C. Pull + set up the VM (run on the VM)

**C1. Clone your repo** (the bootstrap script lives inside it):

```bash
git clone git@github.com:<YOUR_GH_USERNAME>/<REPO_NAME>.git
cd <REPO_NAME>
```

**C2. Run the bootstrap** — installs uv + Docker, clones the two reference
repos (`mini-swe-agent`, `SWE-bench`) **alongside** the project (in the parent
dir, as siblings), creates `.env`, runs `uv sync`:

```bash
bash scripts/bootstrap-vm.sh
```

If Docker was freshly installed, apply the group change once:

```bash
newgrp docker      # or just log out and back in
```

**C3. Add your Nebius key:**

```bash
nano .env          # set NEBIUS_API_KEY=...
```

**C4. Smoke test the agent** (cheap, proves Nebius key + Docker + agent loop).
Run from the **repo root** with the venv active so `mini-extra` is on PATH:

```bash
source .venv/bin/activate
bash scripts/mini-swe-bench-single.sh   # one instance; can take several minutes
```

It's fine to `Ctrl+C` once you've seen it stepping through the agent loop — you
only need it to start cleanly (no auth/setup error).

---

## D. Run the pipeline end-to-end (standalone Airflow)

This validates Phases 1–2 (configurable DAG + structured runs/ + MLflow) before
the Docker Compose deployment in Phase 3.

**D1. Start Airflow** with the Nebius key loaded into its environment (so the
DAG's tasks inherit it). Run from the repo root:

```bash
cd ~/<REPO_NAME>
set -a; source .env; set +a          # export NEBIUS_API_KEY (and MLflow vars)
bash run-airflow-standalone.sh        # serves the UI on :8080
```

**D2. Open the UI.** Forward port `8080` (VSCode Remote-SSH auto-forwards — see
the Ports tab; or `ssh -L 8080:localhost:8080 academy-vm`), then open
http://localhost:8080 and log in `admin` / `admin`.

**D3. Trigger `evaluate_agent` small.** Unpause the DAG, then
**Trigger DAG w/ config** with a tiny slice so it finishes quickly:

```json
{"subset": "verified", "split": "test", "workers": 1, "task_slice": "0:1"}
```

Watch the four tasks go green: `prepare_run -> run_agent -> run_eval ->
summarize_and_log`. (`run_agent` pulls a repo testbed image the first time;
`run_eval` pulls/builds the SWE-bench eval image — both bounded for one task.)

**D4. Inspect the outputs:**

```bash
ls -R runs/                  # runs/<run-id>/ : config, run-agent, run-eval, metrics, manifest
cat runs/*/metrics.json
cat runs/*/manifest.json     # note the embedded mlflow run id + artifact uri
```

**D5. View MLflow.** With no tracking server yet (Phase 3 adds one), runs log to
a local SQLite store at `mlflow.db`:

```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5000
# forward 5000, open http://localhost:5000  -> experiment "swe-bench-agent-eval"
```

You should see one run with params (split, subset, workers, model, task_slice,
cost_limit, dataset_name, git_sha), metrics (resolved/unresolved/resolve_rate…),
and logged artifacts (config.json, metrics.json, manifest.json, preds.json).

**Re-running by run-id:** pass an explicit `run_id` in the trigger config to pin
the output folder name; otherwise it auto-generates `YYYYMMDD-HHMMSS__<model>`.

**Troubleshooting:**

- A red task -> open its log in the Airflow UI, or check
  `runs/<run-id>/run-agent/run-agent.log` / `run-eval/run-eval.log`.
- `mini-extra: command not found` -> venv not found (run from repo root; the
  runner also auto-prepends `.venv/bin` to PATH).
- `No module named 'mlflow'` in `summarize_and_log` -> Airflow runs in an
  isolated uv tool env; the in-process imports (mlflow, boto3) are added via
  `--with` in `run-airflow-standalone.sh`. After editing that script, **restart
  Airflow** and then **Clear** the failed task to rerun it.

> Two execution environments to keep straight: **Python `@task`s** (prepare_run,
> summarize_and_log) run *inside the Airflow process env* -> need mlflow/boto3
> there. **Subprocess tasks** (run_agent, run_eval) shell out into the project
> `.venv` -> need mini-swe-agent/swebench there. Phase 3 (DockerOperator)
> removes this split by running the work in a container image.

---

## E. Production-style deployment (Docker Compose) — Phase 3

Brings up **Airflow (LocalExecutor) + MLflow server + Postgres** as containers,
replacing the standalone script. Do this in stages so each layer is verified
before the next.

**E1. Stop standalone Airflow** (Ctrl+C in its terminal) so ports 8080/5000 are free.

**E2. Fill in the compose vars in `.env`** (the new block in `.env.example`):

```bash
cd ~/mlops-e2e-pipeline
echo "AIRFLOW_UID=$(id -u)"                 >> .env   # own the ./runs files
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env   # socket access
echo "HOST_PROJECT_DIR=$(pwd)"              >> .env
echo "HOST_PARENT_DIR=$(dirname "$(pwd)")"  >> .env
echo "AIRFLOW_JWT_SECRET=$(openssl rand -hex 32)" >> .env   # shared 3.x internal-auth secret
# set AIRFLOW_IMAGE_NAME to match your standalone version:
uv tool run apache-airflow version          # 3.2.2  -> AIRFLOW_IMAGE_NAME=apache/airflow:3.2.2
```

Make sure `NEBIUS_API_KEY` is already in `.env` (it is, from earlier).

**E3. Build the images** (the eval image used by DockerOperator, plus the
Airflow + MLflow images):

```bash
docker build -t mlops-eval:latest .        # eval image from the root Dockerfile
docker compose build                       # airflow + mlflow images
```

**E4. Bring up the stack:**

```bash
docker compose up -d
docker compose ps                          # all services Up / healthy
```

`airflow-init` runs once (db migrate + create the admin user) and exits — that's
expected. Watch logs if anything restarts:

```bash
docker compose logs -f airflow-scheduler
docker compose logs -f mlflow
```

**E5. Verify the stack:**

- Airflow UI -> http://localhost:8080 (forward 8080) — log in `admin` / `admin`,
  confirm the DAGs parse with no import errors.
- MLflow UI -> http://localhost:5000 (forward 5000) — now a real server, no more
  Safari/forwarding quirk; the DAG logs here via `MLFLOW_TRACKING_URI=http://mlflow:5000`.

> At this checkpoint the stack is healthy but the pipeline still runs via the
> standalone-style subprocess DAG. The **DockerOperator DAG** (`evaluate_agent_docker`)
> that runs the agent/eval steps inside the eval image is the next step — it's
> what makes the compose deployment actually execute the pipeline in isolation.

**Common bring-up issues:**

- `permission denied /var/run/docker.sock` -> `DOCKER_GID` doesn't match the host;
  re-set it with `getent group docker | cut -d: -f3` and `docker compose up -d`.
- `airflow-init` fails on `users create` -> the FAB provider is installed in
  `docker/Dockerfile.airflow`; rebuild with `docker compose build --no-cache airflow-init`.
- Image/tag mismatch -> set `AIRFLOW_IMAGE_NAME` to an Airflow 3.x tag that exists.

**Tear down** (keeps volumes): `docker compose down`. Add `-v` to wipe the
Postgres + MLflow data too.

---

## Where the two reference repos live

They are cloned **alongside** this project (as siblings in the parent dir), so
your tree looks like:

```text
<parent>/
  <REPO_NAME>/        <- this project
  mini-swe-agent/     <- reference (provides the agent benchmark config)
  SWE-bench/          <- reference
```

The pipeline finds the agent config automatically (it looks in the sibling
`mini-swe-agent/` by default). To keep the reference repos somewhere else, set
`MSWEA_REPOS_DIR=/path/to/parent` in the environment, or pass an explicit
`config_path` Airflow param. `bootstrap-vm.sh` clones them into the parent for
you.

---

## Updating the VM after future phases

Each later phase (MLflow, Docker, S3) is pushed from your Mac and pulled on the
VM:

```bash
# Mac
git push
# VM
cd <REPO_NAME> && git pull
```
