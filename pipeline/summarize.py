"""Containerized summarize step for the DockerOperator DAG.

Runs INSIDE the eval image (which has mlflow/boto3 via uv) so the Airflow image
stays free of those deps. Given a run id + runs root, it: copies preds, collects
the SWE-bench reports, writes metrics.json, logs the run to MLflow, and writes
manifest.json.

Usage:
    python -m pipeline.summarize --run-id <id> --runs-root /abs/path/to/runs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.layout import RunLayout
from pipeline.manifest import build_manifest
from pipeline.metrics import collect_metrics
from pipeline.mlflow_utils import log_mlflow_run
from pipeline.runner import collect_preds, collect_reports


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize a run and log it to MLflow.")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-root", required=True, help="Absolute path to the runs/ dir.")
    args = ap.parse_args()

    layout = RunLayout(root=Path(args.runs_root) / args.run_id)
    run_config = json.loads(layout.config_json.read_text())

    # Post-process the artifacts the DockerOperator agent/eval steps produced.
    collect_preds(layout)
    collect_reports(run_config, layout)

    metrics = collect_metrics(layout)
    layout.metrics_json.write_text(json.dumps(metrics, indent=2, sort_keys=True))

    mlflow_info = log_mlflow_run(run_config, metrics, layout)
    build_manifest(run_config, layout, metrics, mlflow_info=mlflow_info)

    print(json.dumps({"metrics": metrics, "mlflow": mlflow_info}, indent=2))


if __name__ == "__main__":
    main()
