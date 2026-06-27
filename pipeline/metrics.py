"""Parse SWE-bench evaluation output into a flat, MLflow-friendly metrics dict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.layout import RunLayout


def collect_metrics(layout: RunLayout) -> dict[str, Any]:
    """Read the harness summary + per-instance reports into one metrics dict.

    Falls back gracefully if the summary is missing (e.g. the harness crashed),
    deriving counts from per-instance ``*.report.json`` files instead.
    """
    summary_path = layout.eval_reports_dir / "summary.json"
    metrics: dict[str, Any] = {}

    if summary_path.exists():
        s = json.loads(summary_path.read_text())
        metrics.update(
            {
                "total_instances": s.get("total_instances"),
                "submitted_instances": s.get("submitted_instances"),
                "completed_instances": s.get("completed_instances"),
                "resolved_instances": s.get("resolved_instances"),
                "unresolved_instances": s.get("unresolved_instances"),
                "empty_patch_instances": s.get("empty_patch_instances"),
                "error_instances": s.get("error_instances"),
            }
        )
        submitted = s.get("submitted_instances") or 0
        resolved = s.get("resolved_instances") or 0
        metrics["resolve_rate"] = (resolved / submitted) if submitted else 0.0
    else:
        # Derive from per-instance reports.
        reports = list(layout.eval_reports_dir.glob("*.report.json"))
        resolved = 0
        for rp in reports:
            data = json.loads(rp.read_text())
            # report.json is keyed by instance id.
            for _, body in data.items():
                if body.get("resolved"):
                    resolved += 1
        submitted = len(reports)
        metrics.update(
            {
                "submitted_instances": submitted,
                "resolved_instances": resolved,
                "unresolved_instances": submitted - resolved,
                "resolve_rate": (resolved / submitted) if submitted else 0.0,
            }
        )

    return metrics
