"""Configurable end-to-end coding-agent evaluation pipeline.

    prepare_run -> run_agent -> run_eval -> summarize_and_log

Everything is driven by Airflow Params (no hard-coded experiment values). The
DAG writes a fully reproducible ``runs/<run-id>/`` tree and (Phase 2) logs
params + metrics + artifact references to MLflow.

Trigger from the Airflow UI with "Trigger DAG w/ config", or via CLI:

    airflow dags trigger evaluate_agent \
        --conf '{"subset": "verified", "split": "test", "workers": 5, "task_slice": "0:3"}'
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task
from airflow.models.param import Param

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Make the local ``pipeline`` package importable from within Airflow.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import build_run_config  # noqa: E402
from pipeline.layout import RunLayout, prepare_run_dir  # noqa: E402
from pipeline.runner import run_agent_batch, run_swebench_eval  # noqa: E402
from pipeline.summarize import summarize_run  # noqa: E402

# Runs directory: overridable so it can point at a mounted volume / shared disk.
RUNS_ROOT = Path(os.environ.get("PIPELINE_RUNS_ROOT", PROJECT_ROOT / "runs"))


@dag(
    dag_id="evaluate_agent",
    description="Run mini-swe-agent on a SWE-bench subset and evaluate the patches.",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["mlops", "swe-bench", "evaluation"],
    params={
        # --- required ---
        "split": Param("test", type="string", title="Dataset split"),
        "subset": Param(
            "verified",
            type="string",
            enum=["verified", "lite", "full", "multimodal"],
            title="SWE-bench subset",
        ),
        "workers": Param(5, type="integer", minimum=1, title="Parallel workers"),
        # --- optional but useful ---
        "model": Param(
            "nebius/moonshotai/Kimi-K2.6", type="string", title="Model (LiteLLM id)"
        ),
        "task_slice": Param(
            "0:3", type=["string", "null"], title="Instance slice, e.g. 0:3"
        ),
        "run_id": Param(
            None,
            type=["string", "null"],
            title="Run id (auto-generated if empty)",
        ),
        "cost_limit": Param(
            0, type=["integer", "number", "null"], title="Per-instance cost limit ($)"
        ),
    },
)
def evaluate_agent():
    @task
    def prepare_run(params: dict | None = None) -> dict:
        """Resolve config from params and create runs/<run-id>/config.json."""
        run_config = build_run_config(params or {}, PROJECT_ROOT)
        layout = prepare_run_dir(run_config, RUNS_ROOT)
        print(f"[prepare_run] run_id={run_config['run_id']}")
        print(f"[prepare_run] run dir: {layout.root}")
        print(json.dumps(run_config, indent=2))
        return run_config

    @task
    def run_agent(run_config: dict) -> str:
        """Run mini-swe-agent; return the path to preds.json."""
        layout = RunLayout(root=RUNS_ROOT / run_config["run_id"])
        preds = run_agent_batch(run_config, layout, PROJECT_ROOT)
        print(f"[run_agent] predictions: {preds}")
        return str(preds)

    @task
    def run_eval(run_config: dict, preds_path: str) -> str:
        """Evaluate predictions with the SWE-bench harness."""
        layout = RunLayout(root=RUNS_ROOT / run_config["run_id"])
        eval_dir = run_swebench_eval(run_config, Path(preds_path), layout, PROJECT_ROOT)
        print(f"[run_eval] eval output: {eval_dir}")
        return str(eval_dir)

    @task
    def summarize_and_log(run_config: dict, eval_dir: str) -> dict:
        """Collect results, upload to S3 (optional), log to MLflow, write manifest."""
        layout = RunLayout(root=RUNS_ROOT / run_config["run_id"])
        result = summarize_run(
            layout,
            run_config,
            default_tracking_uri=f"sqlite:///{PROJECT_ROOT / 'mlflow.db'}",
        )
        return result

    cfg = prepare_run()
    preds = run_agent(cfg)
    eval_dir = run_eval(cfg, preds)
    summarize_and_log(cfg, eval_dir)


evaluate_agent()
