"""boto3 client factories. Same code path whether AWS_ENDPOINT_URL points at
moto_server (local dev) or is unset (real AWS) -- the endpoint override is
the only difference, exactly mirroring how Terraform points at moto via
provider endpoints{} (see infra/main.tf).

Reads os.environ directly at call time (not via pipeline.config's
module-level constants) so tests can redirect a client to a different
moto_server instance with monkeypatch.setenv -- config.py's `from module
import NAME` pattern elsewhere copies values at import time, which
monkeypatch.setenv can't retroactively change.
"""
from __future__ import annotations

import os

import boto3


def _client_kwargs() -> dict:
    kwargs = {"region_name": os.getenv("AWS_REGION", "eu-central-1")}
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
        kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID", "test")
        kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
    return kwargs


def s3_client():
    return boto3.client("s3", **_client_kwargs())


def dynamodb_resource():
    return boto3.resource("dynamodb", **_client_kwargs())


def kinesis_client():
    return boto3.client("kinesis", **_client_kwargs())
