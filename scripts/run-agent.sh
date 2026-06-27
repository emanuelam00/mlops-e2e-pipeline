#!/usr/bin/env bash
#
# Parameterized mini-swe-agent batch run.
# Reads its configuration from environment variables so the SAME script works
# whether invoked by a local subprocess (Phase 1) or a DockerOperator (Phase 3).
#
# Required env: SUBSET SPLIT MODEL WORKERS OUTPUT_DIR CONFIG_PATH
# Optional env: TASK_SLICE MSWEA_COST_TRACKING
#
# NOTE: the batch `mini-extra swebench` subcommand does NOT accept --cost-limit
# (only the `swebench-single` subcommand does). For the batch path the agent's
# cost/step limits come from the --config yaml. We still record the cost_limit
# DAG param in config.json / MLflow for provenance.
set -euo pipefail

: "${SUBSET:?Set SUBSET (e.g. verified)}"
: "${SPLIT:?Set SPLIT (e.g. test)}"
: "${MODEL:?Set MODEL (e.g. nebius/moonshotai/Kimi-K2.6)}"
: "${WORKERS:?Set WORKERS (e.g. 5)}"
: "${OUTPUT_DIR:?Set OUTPUT_DIR (trajectories output dir)}"
: "${CONFIG_PATH:?Set CONFIG_PATH (mini-swe-agent benchmark config yaml)}"

export MSWEA_COST_TRACKING="${MSWEA_COST_TRACKING:-ignore_errors}"

args=(
  swebench
  --subset "$SUBSET"
  --split "$SPLIT"
  --model "$MODEL"
  --workers "$WORKERS"
  --config "$CONFIG_PATH"
  -o "$OUTPUT_DIR"
)

# Append optional flags only when provided.
if [[ -n "${TASK_SLICE:-}" ]]; then
  args+=(--slice "$TASK_SLICE")
fi

echo "[run-agent] mini-extra ${args[*]}"
exec mini-extra "${args[@]}"
