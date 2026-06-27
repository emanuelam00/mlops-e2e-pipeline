"""Upload a run's artifacts to S3-compatible Object Storage (Nebius).

Optional and best-effort: if the S3 env vars aren't configured, uploads are
skipped and the pipeline still produces a complete local ``runs/<run-id>/``
folder. When configured, the whole run folder is mirrored to
``s3://<bucket>/<prefix>/<run-id>/`` and the URI is returned so it can be logged
to MLflow and recorded in the manifest.

Env (see .env.example):
    S3_ENDPOINT_URL        e.g. https://storage.eu-north1.nebius.cloud
    S3_BUCKET              target bucket
    S3_PREFIX              key prefix (default: "runs")
    AWS_ACCESS_KEY_ID      / AWS_SECRET_ACCESS_KEY   credentials
    AWS_REGION             e.g. eu-north1 (optional)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pipeline.layout import RunLayout


def _s3_settings() -> dict[str, str] | None:
    """Return S3 settings if fully configured, else None (-> skip uploads)."""
    endpoint = os.environ.get("S3_ENDPOINT_URL")
    bucket = os.environ.get("S3_BUCKET")
    access = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    # Treat placeholder values as unset.
    if not all([endpoint, bucket, access, secret]) or "XXX" in f"{access}{secret}":
        return None
    return {
        "endpoint": endpoint,  # type: ignore[dict-item]
        "bucket": bucket,  # type: ignore[dict-item]
        "prefix": (os.environ.get("S3_PREFIX") or "runs").strip("/"),
        "region": os.environ.get("AWS_REGION", ""),
    }


def _client(s: dict[str, str]):
    import boto3  # imported lazily so the module loads without boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=s["endpoint"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=s["region"] or None,
        # Path-style addressing works for MinIO and Nebius alike (avoids
        # virtual-host bucket subdomains that don't resolve for custom endpoints).
        config=Config(s3={"addressing_style": "path"}),
    )


def _base_key(s: dict[str, str], run_id: str) -> str:
    return f"{s['prefix']}/{run_id}" if s["prefix"] else run_id


def upload_run_dir(layout: RunLayout, run_config: dict[str, Any]) -> str | None:
    """Mirror the whole run folder to Object Storage. Returns the s3:// URI.

    Returns None (and prints a notice) if S3 is not configured.
    """
    s = _s3_settings()
    if s is None:
        print("[storage] S3 not configured -> skipping upload (local run folder kept)")
        return None

    client = _client(s)
    base_key = _base_key(s, run_config["run_id"])
    n = 0
    for path in sorted(layout.root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(layout.root).as_posix()
            client.upload_file(str(path), s["bucket"], f"{base_key}/{rel}")
            n += 1
    uri = f"s3://{s['bucket']}/{base_key}/"
    print(f"[storage] uploaded {n} files -> {uri}")
    return uri


def upload_file(layout: RunLayout, run_config: dict[str, Any], path: Path) -> str | None:
    """Upload/refresh a single file under the run's prefix (e.g. manifest.json)."""
    s = _s3_settings()
    if s is None:
        return None
    client = _client(s)
    base_key = _base_key(s, run_config["run_id"])
    rel = path.relative_to(layout.root).as_posix()
    key = f"{base_key}/{rel}"
    client.upload_file(str(path), s["bucket"], key)
    return f"s3://{s['bucket']}/{key}"
