#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  echo 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this script again.' >&2
  exit 1
fi
if [[ -f .env ]]; then
  exec uv run --frozen --no-dev --env-file .env python -m uvicorn scout.app:create_app --factory --host 127.0.0.1 --port 8090
fi
exec uv run --frozen --no-dev python -m uvicorn scout.app:create_app --factory --host 127.0.0.1 --port 8090
