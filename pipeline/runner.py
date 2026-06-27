"""Run the agent batch and the SWE-bench evaluation.

Phase 1 (easy mode) calls the parameterized shell scripts via subprocess. The
scripts read their configuration from environment variables, so the exact same
scripts are reused unchanged by the ``DockerOperator`` tasks in Phase 3 -- only
the execution environment changes, not the interface.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pipeline.layout import RunLayout


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], log_file: Path) -> None:
    """Run a command, streaming combined stdout/stderr to ``log_file``."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w") as fh:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=fh, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSee log: {log_file}"
        )


def run_agent_batch(run_config: dict[str, Any], layout: RunLayout, project_root: Path) -> Path:
    """Run mini-swe-agent over the selected SWE-bench subset.

    Writes trajectories + ``preds.json`` into ``run-agent/`` and returns the path
    to ``preds.json``.
    """
    script = project_root / "scripts" / "run-agent.sh"
    env = {
        **os.environ,
        "SUBSET": run_config["subset"],
        "SPLIT": run_config["split"],
        "MODEL": run_config["model"],
        "WORKERS": str(run_config["workers"]),
        "CONFIG_PATH": str(project_root / run_config["config_path"]),
        "OUTPUT_DIR": str(layout.trajectories_dir),
        "MSWEA_COST_TRACKING": "ignore_errors",
    }
    if run_config.get("task_slice"):
        env["TASK_SLICE"] = run_config["task_slice"]
    if run_config.get("cost_limit") is not None:
        env["COST_LIMIT"] = str(run_config["cost_limit"])

    _run(
        ["bash", str(script)],
        cwd=project_root,
        env=env,
        log_file=layout.run_agent_dir / "run-agent.log",
    )

    produced = layout.trajectories_dir / "preds.json"
    if not produced.exists():
        raise FileNotFoundError(f"Agent did not produce preds.json at {produced}")
    # Stable convenience copy at run-agent/preds.json.
    shutil.copy2(produced, layout.preds_json)
    return layout.preds_json


def run_swebench_eval(run_config: dict[str, Any], preds_path: Path, layout: RunLayout, project_root: Path) -> Path:
    """Evaluate predictions with the SWE-bench harness.

    The harness writes per-instance logs/reports under the cwd, so we run it with
    cwd=run-eval/. Returns the path to the run-eval directory.
    """
    script = project_root / "scripts" / "run-eval.sh"
    run_id = run_config["run_id"]
    env = {
        **os.environ,
        "DATASET_NAME": run_config["dataset_name"],
        "PREDICTIONS_PATH": str(preds_path),
        "MAX_WORKERS": str(run_config["workers"]),
        # SWE-bench run_id must be filesystem-safe; reuse our run_id but sanitize.
        "RUN_ID": run_id.replace("/", "_"),
    }
    _run(
        ["bash", str(script)],
        cwd=layout.run_eval_dir,
        env=env,
        log_file=layout.run_eval_dir / "run-eval.log",
    )

    # The harness drops a summary json named "<model_slug>.<run_id>.json" in cwd.
    _collect_reports(run_config, layout)
    return layout.run_eval_dir


def _collect_reports(run_config: dict[str, Any], layout: RunLayout) -> None:
    """Move the summary json + per-instance report.json files into reports/."""
    layout.eval_reports_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_config["run_id"].replace("/", "_")
    summary_name = f"{run_config['model_slug']}.{run_id}.json"
    summary = layout.run_eval_dir / summary_name
    if summary.exists():
        shutil.copy2(summary, layout.eval_reports_dir / "summary.json")

    # Gather per-instance report.json from the harness log tree.
    for report in layout.eval_logs_dir.rglob("report.json"):
        instance = report.parent.name
        shutil.copy2(report, layout.eval_reports_dir / f"{instance}.report.json")
