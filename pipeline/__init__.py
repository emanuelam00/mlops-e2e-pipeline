"""Reusable helpers for the coding-agent evaluation pipeline.

The Airflow DAG (``dags/evaluate_agent.py``) stays thin and delegates the real
work to these functions so they can be unit-tested and reused outside Airflow.
"""

from pipeline.config import build_run_config, subset_to_dataset_name
from pipeline.layout import RunLayout, prepare_run_dir
from pipeline.metrics import collect_metrics
from pipeline.manifest import build_manifest
from pipeline.mlflow_utils import log_mlflow_run
from pipeline.runner import (
    collect_preds,
    collect_reports,
    run_agent_batch,
    run_swebench_eval,
)

__all__ = [
    "build_run_config",
    "subset_to_dataset_name",
    "RunLayout",
    "prepare_run_dir",
    "collect_metrics",
    "build_manifest",
    "log_mlflow_run",
    "collect_preds",
    "collect_reports",
    "run_agent_batch",
    "run_swebench_eval",
]
