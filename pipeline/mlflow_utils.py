"""Log a completed evaluation run to MLflow.

One Airflow DAG run == one MLflow run. We log the experiment config as params,
the SWE-bench results as metrics, provenance as tags, and the small structured
artifacts (config.json, metrics.json, manifest.json, preds.json) so the run is
comparable and traceable from the MLflow UI.

Connection is controlled by env vars (see .env.example):
    MLFLOW_TRACKING_URI     e.g. http://localhost:5000 (falls back to ./mlruns)
    MLFLOW_EXPERIMENT_NAME  default: swe-bench-agent-eval
"""

from __future__ import annotations

import os
from numbers import Number
from typing import Any

from pipeline.layout import RunLayout

DEFAULT_EXPERIMENT = "swe-bench-agent-eval"

# Config keys logged as MLflow params (experiment knobs + provenance).
_PARAM_KEYS = (
    "run_id",
    "split",
    "subset",
    "workers",
    "model",
    "task_slice",
    "cost_limit",
    "dataset_name",
    "git_sha",
)


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in metrics.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, Number):
            out[k] = float(v)
    return out


def log_mlflow_run(
    run_config: dict[str, Any],
    metrics: dict[str, Any],
    layout: RunLayout,
    *,
    remote_artifact_uri: str | None = None,
    default_tracking_uri: str | None = None,
) -> dict[str, Any]:
    """Create one MLflow run; return identifiers for the manifest.

    Connection precedence: ``MLFLOW_TRACKING_URI`` env -> ``default_tracking_uri``
    arg -> a local SQLite store next to the run. (MLflow 3.x deprecated the bare
    file store, so we never fall back to ``./mlruns``.)

    Returns a dict with ``mlflow_run_id``, ``experiment``, ``tracking_uri`` and
    the MLflow ``artifact_uri`` so the manifest can cross-reference the run.
    """
    import mlflow  # imported lazily so the DAG parses even without mlflow

    tracking_uri = (
        os.environ.get("MLFLOW_TRACKING_URI")
        or default_tracking_uri
        or f"sqlite:///{layout.root.parent.parent / 'mlflow.db'}"
    )
    mlflow.set_tracking_uri(tracking_uri)
    experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME", DEFAULT_EXPERIMENT)
    mlflow.set_experiment(experiment)

    with mlflow.start_run(run_name=run_config["run_id"]) as run:
        mlflow.log_params(
            {k: run_config.get(k) for k in _PARAM_KEYS if run_config.get(k) is not None}
        )
        mlflow.log_metrics(_numeric_metrics(metrics))
        mlflow.set_tags(
            {
                "run_id": run_config["run_id"],
                "model": run_config.get("model"),
                "dataset_name": run_config.get("dataset_name"),
                "git_sha": run_config.get("git_sha"),
                "local_artifact_dir": str(layout.root),
                "remote_artifact_uri": remote_artifact_uri or "",
            }
        )

        # Log the small, structured artifacts (not the heavy trajectories/logs).
        for path in (
            layout.config_json,
            layout.metrics_json,
            layout.manifest_json,
            layout.preds_json,
        ):
            if path.exists():
                mlflow.log_artifact(str(path))

        info = {
            "mlflow_run_id": run.info.run_id,
            "experiment": experiment,
            "tracking_uri": mlflow.get_tracking_uri(),
            "artifact_uri": mlflow.get_artifact_uri(),
        }

    print(f"[mlflow] logged run {info['mlflow_run_id']} to {info['tracking_uri']}")
    return info
