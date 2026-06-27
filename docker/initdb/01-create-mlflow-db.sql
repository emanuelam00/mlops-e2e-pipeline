-- Runs once on first Postgres init (mounted into /docker-entrypoint-initdb.d).
-- Airflow uses the default `airflow` database; MLflow gets its own `mlflow` DB
-- on the same Postgres instance.
SELECT 'CREATE DATABASE mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')\gexec
GRANT ALL PRIVILEGES ON DATABASE mlflow TO airflow;
