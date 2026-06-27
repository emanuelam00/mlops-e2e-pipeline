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

**C4. Sanity checks:**

```bash
# single-task agent run (cheap smoke test)
bash scripts/mini-swe-bench-single.sh

# Airflow (easy mode)
bash run-airflow-standalone.sh
# then forward 8080 from your Mac:  ssh -L 8080:localhost:8080 academy-vm
# open http://localhost:8080  (login admin/admin) and trigger `evaluate_agent`
```

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
