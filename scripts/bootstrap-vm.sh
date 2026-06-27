#!/usr/bin/env bash
#
# Bootstrap a fresh Nebius (Ubuntu) VM for the evaluation pipeline.
#
# Run this from INSIDE the cloned project repo on the VM:
#     cd ~/mlops-assignment-e2e-ml-pipeline
#     bash scripts/bootstrap-vm.sh
#
# It is idempotent: re-running skips anything already installed/cloned.
# What it does:
#   1. install uv
#   2. install Docker (+ add your user to the docker group)
#   3. clone the two upstream reference repos ALONGSIDE the project
#      (in the parent dir, as siblings -- not inside the project repo)
#   4. create .env from .env.example (you then add NEBIUS_API_KEY)
#   5. uv sync
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
echo "==> Project root: $REPO_ROOT"

# --- 1. uv -----------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1090
  source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
else
  echo "==> uv already installed: $(uv --version)"
fi

# --- 2. Docker -------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "==> Added $USER to the docker group."
  echo "    Log out/in (or run 'newgrp docker') before using docker without sudo."
else
  echo "==> Docker already installed: $(docker --version)"
fi

# --- 3. Upstream reference repos (alongside the project, in the parent) -----
PARENT_DIR="$(dirname "$REPO_ROOT")"
clone_if_missing() {
  local url="$1" dir="$2"
  if [[ -d "$dir/.git" ]]; then
    echo "==> $dir already present, skipping"
  else
    echo "==> Cloning $url -> $dir"
    git clone --depth 1 "$url" "$dir"
  fi
}
clone_if_missing https://github.com/SWE-agent/mini-swe-agent.git "$PARENT_DIR/mini-swe-agent"
clone_if_missing https://github.com/swe-bench/SWE-bench.git "$PARENT_DIR/SWE-bench"

AGENT_CFG="$PARENT_DIR/mini-swe-agent/src/minisweagent/config/benchmarks/swebench.yaml"
if [[ -f "$AGENT_CFG" ]]; then
  echo "==> Found agent benchmark config: $AGENT_CFG"
else
  echo "!!  WARNING: expected agent config not found at $AGENT_CFG"
fi

# --- 4. .env ---------------------------------------------------------------
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example -- add your NEBIUS_API_KEY:"
  echo "    nano .env"
else
  echo "==> .env already exists, leaving it alone"
fi

# --- 5. Dependencies -------------------------------------------------------
echo "==> uv sync"
uv sync

echo
echo "================================================================"
echo " Bootstrap complete."
echo " Next:"
echo "   1) Put your key in .env:        NEBIUS_API_KEY=..."
echo "   2) Sanity check the agent:      bash scripts/mini-swe-bench-single.sh"
echo "   3) Start Airflow (easy mode):   bash run-airflow-standalone.sh"
echo "      then forward port 8080 and open http://localhost:8080"
echo "   (Docker Compose for Airflow+MLflow comes in Phase 3.)"
echo "================================================================"
