"""Summarize a run: collect results, upload artifacts, log to MLflow.

``summarize_run`` is the single implementation shared by both DAGs:
- the standalone DAG calls it from a Python task;
- the DockerOperator DAG runs this module as ``python -m pipeline.summarize``
  inside the eval image (which has mlflow/boto3 via uv).

Sequence: copy preds -> collect SWE-bench reports -> write metrics.json ->
upload run folder to Object Storage (optional) -> log run to MLflow (with the
S3 URI) -> write manifest.json -> refresh the uploaded manifest.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pipeline.layout import RunLayout
from pipeline.manifest import build_manifest
from pipeline.metrics import collect_metrics
from pipeline.mlflow_utils import log_mlflow_run
from pipeline.runner import collect_preds, collect_reports
from pipeline.storage import upload_file, upload_run_dir


def summarize_run(
    layout: RunLayout,
    run_config: dict[str, Any],
    *,
    default_tracking_uri: str | None = None,
) -> dict[str, Any]:
    """Finalize a run; returns ``{metrics, mlflow, s3_uri}``."""
    # Idempotent post-processing of the agent/eval outputs.
    collect_preds(layout)
    collect_reports(run_config, layout)

    metrics = collect_metrics(layout)
    layout.metrics_json.write_text(json.dumps(metrics, indent=2, sort_keys=True))

    # Long-term storage (no-op if S3 isn't configured).
    s3_uri = upload_run_dir(layout, run_config)

    mlflow_info = log_mlflow_run(
        run_config, metrics, layout,
        remote_artifact_uri=s3_uri,
        default_tracking_uri=default_tracking_uri,
    )

    build_manifest(run_config, layout, metrics, artifact_uri=s3_uri, mlflow_info=mlflow_info)
    # Refresh the remote manifest now that it references MLflow + S3.
    if s3_uri:
        upload_file(layout, run_config, layout.manifest_json)

    result = {"metrics": metrics, "mlflow": mlflow_info, "s3_uri": s3_uri}
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize a run and log it to MLflow.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-root", required=True, help="Absolute path to the runs/ dir.")
    args = ap.parse_args()

    layout = RunLayout(root=Path(args.runs_root) / args.run_id)
    run_config = json.loads(layout.config_json.read_text())
    summarize_run(layout, run_config)


if __name__ == "__main__":
    main()
