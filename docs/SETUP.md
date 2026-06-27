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

<a id="docker-group"></a>
**Use Docker without sudo.** The bootstrap adds you to the `docker` group, but
group membership only applies to **new login sessions** — so your current shell
(and any old VSCode terminal) won't have it yet. Activate it, then verify:

```bash
groups                            # is 'docker' listed?
sudo usermod -aG docker "$USER"   # only if it's NOT listed
newgrp docker                     # activate the group in THIS shell
#   (or simpler: close the terminal / reconnect SSH for a fresh login)
docker ps                         # should work WITHOUT sudo
```

If you see `permission denied ... /var/run/docker.sock`, the group isn't active
in this shell — repeat the `newgrp docker` step or reconnect. Don't fall back to
`sudo docker ...`; it creates root-owned images/files that cause trouble later.

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
Airflow + MLflow images). First make sure `docker ps` works without sudo in this
shell — if not, see [Use Docker without sudo](#docker-group) above.

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

- `permission denied ... /var/run/docker.sock` **from your shell** (e.g. on
  `docker build`/`docker compose`) -> your user isn't in the `docker` group in
  this session; see [Use Docker without sudo](#docker-group).
- `permission denied ... /var/run/docker.sock` **from inside a container** (the
  DockerOperator tasks, Phase 3b) -> `DOCKER_GID` doesn't match the host's docker
  group; re-set it with `getent group docker | cut -d: -f3`, put it in `.env`,
  and `docker compose up -d`.
- `airflow-init` fails on `users create` -> the FAB provider is installed in
  `docker/Dockerfile.airflow`; rebuild with `docker compose build --no-cache airflow-init`.
- Image/tag mismatch -> set `AIRFLOW_IMAGE_NAME` to an Airflow 3.x tag that exists.

**Tear down** (keeps volumes): `docker compose down`. Add `-v` to wipe the
Postgres + MLflow data too.

---

## F. Run the DockerOperator pipeline (`evaluate_agent_docker`) — Phase 3b

The `evaluate_agent_docker` DAG runs the agent, evaluation, and summarize steps
inside the **eval image** via `DockerOperator`, with MLflow logging to the
compose MLflow server. Airflow only orchestrates.

**F1. Prereqs** (from Section E): the stack is up, the eval image is built
(`docker build -t mlops-eval:latest .`), and `.env` has `HOST_PROJECT_DIR` and
`HOST_PARENT_DIR`.

> **`EVAL_IMAGE` and `COMPOSE_NETWORK` are optional** — compose already defaults
> them, so you only need to set them if you deviate from the defaults:
> - `EVAL_IMAGE` (default `mlops-eval:latest`) = the `name:tag` you passed to
>   `docker build -t ... .`. Only override if you tagged the image differently.
> - `COMPOSE_NETWORK` (default `mlops-e2e-pipeline_default`) = the compose
>   network name. Verify it matches with `docker network ls | grep default`; only
>   override if your compose project was renamed (e.g. a different repo dir name).

After editing `.env`, apply it: `docker compose up -d`.

**F2. Trigger** `evaluate_agent_docker` from the Airflow UI (http://localhost:8080)
with a small config:

```json
{"subset": "verified", "split": "test", "workers": 1, "task_slice": "0:1"}
```

Watch `prepare_run -> run_agent -> run_eval -> summarize_and_log`. The three
docker tasks each launch a transient eval container (visible via `docker ps`).

**F3. Verify** (same artifacts as the standalone run, now produced via Docker):

```bash
ls -R runs/<run-id>/
cat runs/<run-id>/metrics.json
```
The run appears in the MLflow UI (http://localhost:5000) under
`swe-bench-agent-eval`, logged by the summarize container over the compose network.

**How the docker-out-of-docker paths work:** DockerOperator talks to the HOST
docker daemon, so bind mounts use HOST paths. The DAG mounts the project and the
sibling `mini-swe-agent` at their *identical* host paths inside each eval
container, so every absolute path (runs dir, agent config, scripts) is the same
in and out of the container — no path translation. The socket is mounted so the
agent/eval steps (and SWE-bench's per-task containers) can spawn sub-containers.

**Common issues:**

- `Error: No such image: mlops-eval:latest` -> build it: `docker build -t mlops-eval:latest .`.
- summarize can't reach MLflow (`Connection refused http://mlflow:5000`) ->
  `COMPOSE_NETWORK` doesn't match; set it to the real network from
  `docker network ls | grep default` and `docker compose up -d`.
- `permission denied /var/run/docker.sock` inside the eval container -> the
  `DOCKER_GID` must match the host docker group (Section E .env).
- agent auth errors -> `NEBIUS_API_KEY` must be in `.env` (the DAG passes it through).

---

## G. Object Storage — Phase 4

When the S3 env vars are set, `summarize_and_log` uploads `runs/<run-id>/` to
Object Storage, logs the URI to MLflow, and records it in `manifest.json`
(`remote_artifact_uri`). It's optional — leave `AWS_*` as `XXX` and the step is
skipped, with the local run folder still complete. The uploader speaks plain S3,
so it works against **any** S3-compatible endpoint.

### Option A — local MinIO (default, no external creds)

The compose stack includes a `minio` service (S3-compatible) and a `minio-init`
one-shot that creates the bucket. The pipeline uploads here exactly as it would
to Nebius. Use this when you don't have Nebius IAM access to mint access keys.

**G1.** Set these in `.env` (MinIO root creds == the `AWS_*` creds; secret must
be ≥ 8 chars):

```bash
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=mlops-eval-artifacts
S3_PREFIX=runs
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin123
AWS_REGION=us-east-1
```

**G2.** Bring it up and run:
```bash
docker compose up -d                 # starts minio + creates the bucket
# trigger evaluate_agent_docker from the UI
```

**G3.** Verify: open the MinIO console at http://localhost:9001 (forward 9001),
log in with the `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` values, and browse the
bucket → `runs/<run-id>/`. Or from a shell:
```bash
docker compose exec minio mc alias set local http://localhost:9000 "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY"
docker compose exec minio mc ls -r "local/$S3_BUCKET"
```

### Option B — Nebius Object Storage (if you have access keys)

Nebius S3 keys belong to a **service account** under IAM (not your user), so you
need IAM permission to create them. If you do: create a service account, give it
a storage role, mint an access key (console: IAM → Service accounts → Access
keys; or the Nebius CLI), create a bucket, and set in `.env`:

```bash
S3_ENDPOINT_URL=https://storage.eu-north1.nebius.cloud
S3_BUCKET=<your-bucket>
AWS_ACCESS_KEY_ID=<access-key-id>
AWS_SECRET_ACCESS_KEY=<access-key-secret>
AWS_REGION=eu-north1
```
Then `docker compose up -d` and trigger the DAG. (No `minio` service needed, but
leaving it running is harmless.)

> Screenshots for the report go in `screenshots/`: `airflow_dag.png`,
> `mlflow_runs.png`, `object_storage_artifacts.png` (the MinIO/Nebius bucket view).

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
