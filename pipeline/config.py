"""Build a fully-resolved run configuration from Airflow params.

No experiment values are hard-coded here: every knob comes from the params the
DAG exposes (with sensible documented defaults). ``build_run_config`` is the
single source of truth that every downstream task reads from ``config.json``.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import Any

# Map the agent-side ``--subset`` to the SWE-bench evaluation ``--dataset_name``.
# These are the two places the same logical dataset is named differently.
SUBSET_TO_DATASET: dict[str, str] = {
    "verified": "princeton-nlp/SWE-bench_Verified",
    "lite": "princeton-nlp/SWE-bench_Lite",
    "full": "princeton-nlp/SWE-bench",
    "test": "princeton-nlp/SWE-bench",
    "multimodal": "princeton-nlp/SWE-bench_Multimodal",
}

DEFAULTS: dict[str, Any] = {
    "split": "test",
    "subset": "verified",
    "workers": 5,
    "model": "nebius/moonshotai/Kimi-K2.6",
    "task_slice": "0:3",
    "cost_limit": 0,
    # Path (relative to project root) to the mini-swe-agent benchmark config.
    "config_path": "mini-swe-agent/src/minisweagent/config/benchmarks/swebench.yaml",
}


def subset_to_dataset_name(subset: str) -> str:
    """Resolve the SWE-bench dataset name for a given agent subset."""
    key = subset.strip().lower()
    if key not in SUBSET_TO_DATASET:
        raise ValueError(
            f"Unknown subset {subset!r}. Known subsets: {sorted(SUBSET_TO_DATASET)}"
        )
    return SUBSET_TO_DATASET[key]


def _git_sha(project_root: str | os.PathLike[str]) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _default_run_id(model: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    model_slug = model.replace("/", "__").replace(":", "_")
    return f"{ts}__{model_slug}"


def build_run_config(params: dict[str, Any], project_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Merge Airflow params with defaults into a complete, serializable config.

    Parameters
    ----------
    params:
        The Airflow DAG run params (``context["params"]``).
    project_root:
        Repo root, used to record provenance (git sha) and resolve config paths.
    """
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None}}

    model = str(p["model"])
    run_id = str(p.get("run_id") or _default_run_id(model))
    subset = str(p["subset"])

    config = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # --- experiment knobs (all overridable from Airflow) ---
        "split": str(p["split"]),
        "subset": subset,
        "workers": int(p["workers"]),
        "model": model,
        "task_slice": str(p["task_slice"]) if p.get("task_slice") else None,
        "cost_limit": p.get("cost_limit"),
        "config_path": str(p["config_path"]),
        # --- derived ---
        "dataset_name": subset_to_dataset_name(subset),
        "model_slug": model.replace("/", "__"),
        # --- provenance ---
        "git_sha": _git_sha(project_root),
        "project_root": str(project_root),
    }
    return config
