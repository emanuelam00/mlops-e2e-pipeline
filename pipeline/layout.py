"""Canonical on-disk layout for a single run.

Every run produces the same tree so that handing someone ``runs/<run-id>/`` is
enough to reconstruct the whole experiment::

    runs/<run-id>/
      config.json
      run-agent/
        preds.json
        trajectories/
      run-eval/
        logs/
        reports/
      metrics.json
      manifest.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunLayout:
    """Resolved absolute paths for one run's artifact tree."""

    root: Path  # runs/<run-id>/

    @property
    def config_json(self) -> Path:
        return self.root / "config.json"

    @property
    def run_agent_dir(self) -> Path:
        return self.root / "run-agent"

    @property
    def trajectories_dir(self) -> Path:
        return self.run_agent_dir / "trajectories"

    @property
    def preds_json(self) -> Path:
        # Convenience copy at a stable path; mini-swe-agent writes the original
        # into trajectories/preds.json.
        return self.run_agent_dir / "preds.json"

    @property
    def run_eval_dir(self) -> Path:
        return self.root / "run-eval"

    @property
    def eval_logs_dir(self) -> Path:
        return self.run_eval_dir / "logs"

    @property
    def eval_reports_dir(self) -> Path:
        return self.run_eval_dir / "reports"

    @property
    def metrics_json(self) -> Path:
        return self.root / "metrics.json"

    @property
    def manifest_json(self) -> Path:
        return self.root / "manifest.json"


def prepare_run_dir(run_config: dict[str, Any], runs_root: str | Path) -> RunLayout:
    """Create the run directory tree and persist ``config.json``.

    Returns a :class:`RunLayout` with all the paths downstream tasks need.
    """
    layout = RunLayout(root=Path(runs_root) / run_config["run_id"])
    for d in (
        layout.root,
        layout.run_agent_dir,
        layout.trajectories_dir,
        layout.run_eval_dir,
        layout.eval_logs_dir,
        layout.eval_reports_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    layout.config_json.write_text(json.dumps(run_config, indent=2, sort_keys=True))
    return layout
