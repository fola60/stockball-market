#!/usr/bin/env bash
set +x
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON_BIN:-python3}" "$script_dir/remote_ingestion.py" "$@"
