"""Production-style evaluation pipeline using DockerOperator.

Same logical workflow as ``evaluate_agent`` (the standalone/subprocess DAG), but
the agent, evaluation, and summarize steps run inside the isolated **eval image**
instead of as local subprocesses:

    prepare_run (python) -> run_agent (docker) -> run_eval (docker) -> summarize (docker)

Designed for the docker-compose deployment. Airflow stays a thin orchestrator;
all heavy deps (mini-swe-agent, swebench, mlflow) live in the eval image.

KEY: Docker-out-of-docker path handling. DockerOperator launches containers via
the HOST docker daemon, so bind-mount paths must be HOST paths. We mount the
project and the sibling mini-swe-agent at their identical host paths inside the
eval containers, so every absolute path is the same in and out of the container.
Configure via env (set in docker-compose / .env):
    HOST_PROJECT_DIR, HOST_PARENT_DIR, EVAL_IMAGE, COMPOSE_NETWORK,
    MLFLOW_TRACKING_URI, MLFLOW_EXPERIMENT_NAME, NEBIUS_API_KEY
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task
from airflow.models.param import Param
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import build_run_config  # noqa: E402
from pipeline.layout import prepare_run_dir  # noqa: E402

# --- host-side locations (the host daemon resolves DockerOperator mounts) ------
HOST_PROJECT_DIR = os.environ.get("HOST_PROJECT_DIR", str(PROJECT_ROOT))
HOST_PARENT_DIR = os.environ.get("HOST_PARENT_DIR", str(Path(HOST_PROJECT_DIR).parent))
HOST_MINI_SWE_AGENT = f"{HOST_PARENT_DIR}/mini-swe-agent"
HOST_RUNS_DIR = f"{HOST_PROJECT_DIR}/runs"
HOST_AGENT_CONFIG = f"{HOST_MINI_SWE_AGENT}/src/minisweagent/config/benchmarks/swebench.yaml"

EVAL_IMAGE = os.environ.get("EVAL_IMAGE", "mlops-eval:latest")
COMPOSE_NETWORK = os.environ.get("COMPOSE_NETWORK", "mlops-e2e-pipeline_default")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MLFLOW_EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", "swe-bench-agent-eval")

# Airflow's own view of the runs dir (bind-mounted to HOST_RUNS_DIR).
RUNS_ROOT = Path(os.environ.get("PIPELINE_RUNS_ROOT", PROJECT_ROOT / "runs"))

# Jinja snippet pulling the run_id that prepare_run pushed to XCom.
RID = "{{ ti.xcom_pull(task_ids='prepare_run')['run_id'] }}"


def _xcom(field: str) -> str:
    return "{{ ti.xcom_pull(task_ids='prepare_run')['" + field + "'] }}"


def _common_mounts() -> list[Mount]:
    """Mount project + sibling repo at identical host paths, plus the socket."""
    return [
        Mount(source=HOST_PROJECT_DIR, target=HOST_PROJECT_DIR, type="bind"),
        Mount(source=HOST_MINI_SWE_AGENT, target=HOST_MINI_SWE_AGENT, type="bind"),
        Mount(source="/var/run/docker.sock", target="/var/run/docker.sock", type="bind"),
    ]


_docker_defaults = dict(
    image=EVAL_IMAGE,
    docker_url="unix://var/run/docker.sock",
    network_mode=COMPOSE_NETWORK,  # gives internet + reaches the mlflow service
    auto_remove="success",
    mount_tmp_dir=False,
    mounts=_common_mounts(),
)


@dag(
    dag_id="evaluate_agent_docker",
    description="DockerOperator pipeline: agent + eval run in the isolated eval image.",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["mlops", "swe-bench", "evaluation", "docker"],
    params={
        "split": Param("test", type="string", title="Dataset split"),
        "subset": Param(
            "verified", type="string",
            enum=["verified", "lite", "full", "multimodal"], title="SWE-bench subset",
        ),
        "workers": Param(5, type="integer", minimum=1, title="Parallel workers"),
        "model": Param("nebius/moonshotai/Kimi-K2.6", type="string", title="Model"),
        "task_slice": Param("0:3", type=["string", "null"], title="Instance slice"),
        "run_id": Param(None, type=["string", "null"], title="Run id (auto if empty)"),
        "cost_limit": Param(0, type=["integer", "number", "null"], title="Cost limit ($)"),
    },
)
def evaluate_agent_docker():
    @task
    def prepare_run(params: dict | None = None) -> dict:
        """Resolve config (with HOST agent-config path) and create the run dir."""
        p = dict(params or {})
        # Record the HOST path to the agent config, so config.json is valid for
        # the eval containers (which see the sibling repo at the host path).
        p.setdefault("config_path", HOST_AGENT_CONFIG)
        run_config = build_run_config(p, PROJECT_ROOT)
        prepare_run_dir(run_config, RUNS_ROOT)
        print(f"[prepare_run] run_id={run_config['run_id']} -> {RUNS_ROOT / run_config['run_id']}")
        return run_config

    cfg = prepare_run()

    run_agent = DockerOperator(
        task_id="run_agent",
        command=["bash", f"{HOST_PROJECT_DIR}/scripts/run-agent.sh"],
        environment={
            "SUBSET": _xcom("subset"),
            "SPLIT": _xcom("split"),
            "MODEL": _xcom("model"),
            "WORKERS": _xcom("workers"),
            "TASK_SLICE": "{{ ti.xcom_pull(task_ids='prepare_run')['task_slice'] or '' }}",
            "CONFIG_PATH": HOST_AGENT_CONFIG,
            "OUTPUT_DIR": f"{HOST_RUNS_DIR}/{RID}/run-agent/trajectories",
            "MSWEA_COST_TRACKING": "ignore_errors",
            "NEBIUS_API_KEY": os.environ.get("NEBIUS_API_KEY", ""),
        },
        **_docker_defaults,
    )

    run_eval = DockerOperator(
        task_id="run_eval",
        # Harness writes relative to cwd -> run inside the run-eval dir.
        command=[
            "bash", "-c",
            f'cd "{HOST_RUNS_DIR}/{RID}/run-eval" && bash "{HOST_PROJECT_DIR}/scripts/run-eval.sh"',
        ],
        environment={
            "DATASET_NAME": _xcom("dataset_name"),
            "PREDICTIONS_PATH": f"{HOST_RUNS_DIR}/{RID}/run-agent/trajectories/preds.json",
            "MAX_WORKERS": _xcom("workers"),
            "RUN_ID": RID,
        },
        **_docker_defaults,
    )

    summarize = DockerOperator(
        task_id="summarize_and_log",
        working_dir=HOST_PROJECT_DIR,
        command=["python", "-m", "pipeline.summarize", "--run-id", RID, "--runs-root", HOST_RUNS_DIR],
        environment={
            "PYTHONPATH": HOST_PROJECT_DIR,
            "MLFLOW_TRACKING_URI": MLFLOW_TRACKING_URI,
            "MLFLOW_EXPERIMENT_NAME": MLFLOW_EXPERIMENT_NAME,
        },
        **_docker_defaults,
    )

    cfg >> run_agent >> run_eval >> summarize


evaluate_agent_docker()
