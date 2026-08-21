#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_DIR="${F1_CI_ARTIFACT_DIR:-.ci/f1-operational-profile}"
EXPECTED_HEAD="0005_f1_runtime_acl"
mkdir -p "$ARTIFACT_DIR"

python scripts/ci/normalize_ci_line_endings.py
uv sync --all-groups

uv run alembic upgrade head
actual_head="$(psql -Atc 'SELECT version_num FROM alembic_version')"
if [[ "$actual_head" != "$EXPECTED_HEAD" ]]; then
  echo "unexpected Alembic head: expected $EXPECTED_HEAD, got $actual_head" >&2
  exit 1
fi

uv run pytest \
  tests/integration/f1_operational_profile/test_schema.py \
  tests/integration/f1_operational_profile/test_runtime_privileges.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/schema.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_business_info.py \
  tests/integration/f1_operational_profile/test_catalog_contextual_discovery.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/business-info.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_operational_commands.py \
  tests/integration/f1_operational_profile/test_operational_profile_commands.py \
  tests/integration/f1_operational_profile/test_contextual_config_commands.py \
  tests/integration/f1_operational_profile/test_contextual_supply_lifecycle_commands.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/semantic-commands.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_contextual_booking.py \
  tests/integration/f1_operational_profile/test_contextual_shared_capacity.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/contextual-booking.xml"

# F1 is post-baseline evolution, so the production head must continue to satisfy
# the released V3 booking contracts rather than replacing them.
uv run pytest \
  tests/integration/v3_booking_core \
  tests/integration/v3_booking_commitments \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/v3-booking-regression.xml"
