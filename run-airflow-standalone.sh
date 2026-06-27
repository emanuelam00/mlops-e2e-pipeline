set -euo pipefail

export AIRFLOW_HOME=~/airflow
export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/dags
export AIRFLOW__CORE__LOAD_EXAMPLES=false

mkdir -p $AIRFLOW_HOME

echo '{"admin": "admin"}' > $AIRFLOW_HOME/simple_auth_manager_passwords.json.generated

# Airflow runs in an isolated uv tool env. The DAG's Python tasks import some
# libraries IN-PROCESS (mlflow for tracking, boto3 for the Phase 4 S3 upload),
# so we add them to that env with --with. The agent/eval tasks instead shell out
# into the project .venv (mini-swe-agent, swebench), so those stay separate.
uv tool run \
  --with mlflow \
  --with boto3 \
  apache-airflow standalone
