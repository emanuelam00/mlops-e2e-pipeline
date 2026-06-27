"""Build manifest.json -- the index that points to every important artifact.

The manifest makes a run self-describing: it records the config, the key file
paths (relative to the run root, so it stays valid after the folder is moved or
uploaded to object storage), the metrics, and where the full artifacts live.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.layout import RunLayout


def _rel(path: Path, root: Path) -> str | None:
    return str(path.relative_to(root)) if path.exists() else None


def _count_files(parent: Path, pattern: str) -> int:
    return len(list(parent.glob(pattern))) if parent.exists() else 0


def _count_dirs(parent: Path) -> int:
    if not parent.exists():
        return 0
    return sum(1 for p in parent.iterdir() if p.is_dir())


def build_manifest(
    run_config: dict[str, Any],
    layout: RunLayout,
    metrics: dict[str, Any],
    *,
    artifact_uri: str | None = None,
    mlflow_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble and persist ``manifest.json``; returns the manifest dict."""
    root = layout.root
    manifest = {
        "run_id": run_config["run_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": run_config.get("git_sha"),
        "config": run_config,
        "metrics": metrics,
        "artifacts": {
            "config": _rel(layout.config_json, root),
            "preds": _rel(layout.preds_json, root),
            "trajectories": _rel(layout.trajectories_dir, root),
            "eval_logs": _rel(layout.eval_logs_dir, root),
            "eval_reports": _rel(layout.eval_reports_dir, root),
            "metrics": _rel(layout.metrics_json, root),
        },
        "counts": {
            "trajectories": _count_dirs(layout.trajectories_dir),
            "instance_reports": _count_files(layout.eval_reports_dir, "*.report.json"),
        },
        # MLflow cross-reference: from this folder you can find the tracked run.
        "mlflow": mlflow_info,
        # Where the full artifacts live long-term (set by the S3 upload task).
        "remote_artifact_uri": artifact_uri,
    }
    layout.manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
