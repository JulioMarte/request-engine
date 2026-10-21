#!/usr/bin/env bash
# DEVELOPMENT-ONLY wrapper: ./scripts/dev/local_stack.sh up|status|down [--volumes]
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
exec uv run python scripts/dev/local_stack.py "$@"
