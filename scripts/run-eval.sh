#!/usr/bin/env bash
#
# Parameterized SWE-bench evaluation.
# Reads its configuration from environment variables. The harness writes its
# logs/reports relative to the current working directory, so the caller is
# expected to invoke this with cwd set to runs/<run-id>/run-eval/.
#
# Required env: DATASET_NAME PREDICTIONS_PATH MAX_WORKERS RUN_ID
set -euo pipefail

: "${DATASET_NAME:?Set DATASET_NAME (e.g. princeton-nlp/SWE-bench_Verified)}"
: "${PREDICTIONS_PATH:?Set PREDICTIONS_PATH (path to preds.json)}"
: "${MAX_WORKERS:?Set MAX_WORKERS (e.g. 5)}"
: "${RUN_ID:?Set RUN_ID}"

echo "[run-eval] evaluating $PREDICTIONS_PATH against $DATASET_NAME (run_id=$RUN_ID)"
exec python -m swebench.harness.run_evaluation \
  --dataset_name "$DATASET_NAME" \
  --predictions_path "$PREDICTIONS_PATH" \
  --max_workers "$MAX_WORKERS" \
  --run_id "$RUN_ID"
