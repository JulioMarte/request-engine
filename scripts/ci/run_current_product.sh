#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

ARTIFACT_DIR="${CURRENT_PRODUCT_CI_ARTIFACT_DIR:-.ci/current-product}"
mkdir -p "$ARTIFACT_DIR"

python scripts/ci/normalize_ci_line_endings.py
uv sync --all-groups

# Current-product proof follows the repository's accepted migration head. A
# feature/rebaseline may intentionally change that head; the safety condition is
# one unambiguous repository head and a database actually upgraded to it, not a
# permanent equality to the revision that happened to introduce F1.
mapfile -t repository_heads < <(uv run alembic heads | awk 'NF {print $1}')
if [[ ${#repository_heads[@]} -ne 1 ]]; then
  printf 'expected exactly one Alembic head, found %s: %s\n' \
    "${#repository_heads[@]}" "${repository_heads[*]:-<none>}" >&2
  exit 1
fi
expected_head="${repository_heads[0]}"

uv run alembic upgrade head
actual_head="$(psql -Atc 'SELECT version_num FROM alembic_version')"
if [[ "$actual_head" != "$expected_head" ]]; then
  echo "unexpected Alembic head: repository=$expected_head database=$actual_head" >&2
  exit 1
fi

# Current schema/runtime and operational-profile guarantees.
uv run pytest \
  tests/integration/f1_operational_profile/test_schema.py \
  tests/integration/f1_operational_profile/test_runtime_privileges.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/schema.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_business_info.py \
  tests/integration/f1_operational_profile/test_catalog_contextual_discovery.py \
  tests/integration/f1_operational_profile/test_foreign_tenant_opacity.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/business-info.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_operational_commands.py \
  tests/integration/f1_operational_profile/test_operational_profile_commands.py \
  tests/integration/f1_operational_profile/test_contextual_config_commands.py \
  tests/integration/f1_operational_profile/test_contextual_supply_lifecycle_commands.py \
  tests/integration/f1_operational_profile/test_resource_wide_schedule_exception_command.py \
  tests/integration/f1_operational_profile/test_semantic_surface_gaps.py \
  tests/integration/f1_operational_profile/test_public_contact_normalization.py \
  tests/integration/f1_operational_profile/test_contextual_terms_supersession.py \
  tests/integration/f1_operational_profile/test_contextual_configuration_races.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/semantic-commands.xml"

uv run pytest \
  tests/integration/f1_operational_profile/test_contextual_booking.py \
  tests/integration/f1_operational_profile/test_context_only_commercial_booking.py \
  tests/integration/f1_operational_profile/test_multi_resource_commercial_provenance.py \
  tests/integration/f1_operational_profile/test_contextual_booking_races.py \
  tests/integration/f1_operational_profile/test_contextual_booking_additional_races.py \
  tests/integration/f1_operational_profile/test_contextual_temporal_provenance.py \
  tests/integration/f1_operational_profile/test_contextual_shared_capacity.py \
  tests/integration/f1_operational_profile/test_contextual_dst_and_authority.py \
  tests/integration/f1_operational_profile/test_capability_flow.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/contextual-booking.xml"

# F2 is part of current product truth, not a detached feature-local proof. These
# tests exercise the dedicated discovery role, exact Publication/Mapping fences,
# opaque handoff lifecycle and stale/no-side-effect commitment behavior against
# the same PostgreSQL head used by the production-like suites below.
uv run pytest \
  tests/db/test_f2_discovery_candidate_fence.py \
  tests/db/test_f2_discovery_handoff.py \
  tests/db/test_f2_discovery_handoff_lifecycle.py \
  tests/db/test_f2_discovery_privileges.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/f2-discovery-db.xml"

# Production-like HTTP/runtime journeys are current-product evidence. They run
# against current Alembic head with real app/worker runtime roles and PostgreSQL;
# they must not disappear merely because V3 historical execution was separated.
uv run pytest \
  tests/e2e \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/e2e.xml"

# These suites were introduced during V3 but protect still-current booking,
# capacity, revalidation and race guarantees. Keep them in the current-product
# gate because of the guarantees they prove, not because current architecture is
# required to remain structurally V3.
uv run pytest \
  tests/integration/v3_booking_core \
  tests/integration/v3_booking_commitments \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/booking-capacity-regression.xml"
