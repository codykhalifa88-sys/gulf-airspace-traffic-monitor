#!/usr/bin/env bash
# Fetches a portable Terraform binary into ./bin/ — no sudo/apt needed.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(curl -s https://checkpoint-api.hashicorp.com/v1/check/terraform | python3 -c "import sys,json; print(json.load(sys.stdin)['current_version'])")"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) TF_ARCH="amd64" ;;
  aarch64|arm64) TF_ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

mkdir -p bin
curl -sL "https://releases.hashicorp.com/terraform/${VERSION}/terraform_${VERSION}_linux_${TF_ARCH}.zip" -o /tmp/terraform.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/terraform.zip').extractall('bin')"
chmod +x bin/terraform
./bin/terraform version
