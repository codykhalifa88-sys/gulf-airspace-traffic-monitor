"""Session-scoped fixtures for integration tests: a dedicated moto_server
instance on its own port (separate from any local dev instance a developer
might already have running) and its own Terraform state file, so the test
suite never collides with a developer's own environment or leftover data.
Same pattern as the ev-charging-gap-analysis sibling."""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
import requests

MOTO_SERVER_BIN = os.path.join(os.path.dirname(sys.executable), "moto_server")
TEST_MOTO_PORT = int(os.environ.get("TEST_MOTO_PORT", "5099"))
TEST_MOTO_ENDPOINT = f"http://localhost:{TEST_MOTO_PORT}"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFRA_DIR = os.path.join(REPO_ROOT, "infra")
TEST_TFSTATE = "/tmp/gulf_airspace_test.tfstate"


@pytest.fixture(scope="session")
def moto_server():
    proc = subprocess.Popen(
        [MOTO_SERVER_BIN, "-p", str(TEST_MOTO_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            requests.get(f"{TEST_MOTO_ENDPOINT}/moto-api/", timeout=1)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("moto_server did not become healthy in time")

    yield TEST_MOTO_ENDPOINT

    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def terraform_bin():
    path = os.path.join(REPO_ROOT, "bin", "terraform")
    if not os.path.exists(path):
        pytest.skip("terraform binary not found at ./bin/terraform -- run scripts/fetch_terraform_binary.sh")
    return path


@pytest.fixture(scope="session")
def applied_infra(moto_server, terraform_bin):
    """Applies the real Terraform config against the test moto_server
    instance, using a dedicated state file so it never touches a
    developer's own infra/terraform.tfstate."""
    apply_args = [
        terraform_bin,
        f"-chdir={INFRA_DIR}",
        "apply",
        f"-state={TEST_TFSTATE}",
        "-auto-approve",
        "-input=false",
        "-var", f"moto_endpoint={moto_server}",
    ]
    subprocess.run([terraform_bin, f"-chdir={INFRA_DIR}", "init", "-input=false"], check=True)
    subprocess.run(apply_args, check=True, capture_output=True, text=True)

    yield moto_server

    subprocess.run(
        [
            terraform_bin,
            f"-chdir={INFRA_DIR}",
            "destroy",
            f"-state={TEST_TFSTATE}",
            "-auto-approve",
            "-input=false",
            "-var", f"moto_endpoint={moto_server}",
        ],
        check=False,
    )


@pytest.fixture()
def aws_env(monkeypatch, applied_infra):
    """Points pipeline.aws_clients at the test moto_server for one test."""
    monkeypatch.setenv("AWS_ENDPOINT_URL", applied_infra)
