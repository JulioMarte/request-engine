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

# Audit the effective PostgreSQL model, not the migration history that produced
# it. The catalog artifact is the primary evidence for pre-rebaseline cohesion.
uv run python scripts/db/export_schema_catalog.py \
  --output "$ARTIFACT_DIR/schema-catalog.json"
uv run python scripts/db/analyze_schema_cohesion.py \
  --catalog "$ARTIFACT_DIR/schema-catalog.json" \
  --output "$ARTIFACT_DIR/schema-cohesion-analysis.json"

# Before the historical migration chain is ever replaced, prove that a
# schema-only PostgreSQL export of this exact audited head can reproduce the
# effective model in a second empty database. This is evidence only: the current
# Alembic chain remains the source migration authority until clean-cluster role
# bootstrap and full candidate-baseline proofs are also green.
bash scripts/db/prove_rebaseline_reproduction.sh "$ARTIFACT_DIR"

# Current schema/runtime and operational-profile guarantees.
uv run pytest \
  tests/integration/f1_operational_profile/test_schema.py \
  tests/integration/f1_operational_profile/test_runtime_privileges.py \
  tests/db/test_runtime_immutable_table_privileges.py \
  tests/db/test_runtime_role_topology.py \
  tests/db/test_runtime_privilege_boundary.py \
  tests/db/test_schema_index_cohesion.py \
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

# F2 is part of current product truth, not a detached feature-local proof. Run the
# complete F2 PostgreSQL proof set so the exact-head gate covers candidate and
# handoff fences, privileges, public projection, publication concurrency, exact
# radius semantics and taxonomy lifecycle against the production migration head.
uv run pytest \
  tests/db/test_f2_*.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/f2-discovery-db.xml"

# F3 live-service operations are current product truth. Run the complete F3
# PostgreSQL proof set so lifecycle, temporal authority, tenant opacity and
# adversarial races execute against the same accepted migration head.
uv run pytest \
  tests/db/test_f3_*.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/f3-live-service-db.xml"

# F4 projections are advisory reads over current product truth. Keep their
# PostgreSQL authority, tenant-opacity, snapshot and no-lock proofs on the same
# accepted migration head so customer projection safety cannot regress silently.
uv run pytest \
  tests/db/test_f4_*.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/f4-live-capacity-db.xml"

# The deterministic F4 workload/deduplication rules are current contracts even
# though they do not require PostgreSQL themselves. Their JUnit evidence belongs
# in the same current guarantee packet as the DB-backed F4 proofs.
uv run pytest \
  tests/modules/live_capacity/test_planned_duration_fallback.py \
  tests/modules/live_capacity/test_deduplication.py \
  -q --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/live-capacity-contract.xml"

# Tenant RLS catalog isolation is current-product truth. Run the adversarial
# catalog enumeration against the accepted Alembic head so post-baseline tenant
# tables cannot silently ship without FORCE RLS and a tenant-bound policy.
uv run pytest \
  tests/db/test_v3_tenant_isolation_adversarial.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/tenant-isolation-adversarial.xml"

# F5 operational recovery is current product truth. Keep its workflow/RLS/
# freshness and escalation-fact PostgreSQL proofs on the same accepted
# migration head so recovery guarantees cannot regress silently.
uv run pytest \
  tests/db/test_f5_*.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/f5-recovery-db.xml"

# The reviewed runtime function surface is fail-closed truth: the app role may
# execute only the functions an accepted migration granted. Run the real-login
# inventory on current HEAD so new grants cannot ship outside review.
uv run pytest \
  tests/db/test_v3_app_function_privilege_inventory.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/app-function-inventory.xml"

# HTTP idempotency is a current externally-retryable command guarantee. These
# proofs carry the invariant evidence that the broader E2E idempotency coverage
# alone does not label explicitly.
uv run pytest \
  tests/integration/v3_first_vertical/test_http_idempotency_failure.py \
  tests/integration/v3_first_vertical/test_http_request_idempotency_failure.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/idempotency.xml"

# Worker crash/retry, lease fencing, notification escalation and provider-outcome
# interpretation are current product guarantees. Their paths are historical V3
# names only; execution here is based on the invariants they prove.
uv run pytest \
  tests/integration/v3_worker_runtime/test_process_crash_recovery.py \
  tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py \
  tests/integration/v3_worker_runtime/test_escalation_step_race.py \
  tests/integration/v3_worker_runtime/test_escalation_schema.py \
  tests/integration/v3_worker_runtime/test_escalation_replay_and_window.py \
  tests/integration/v3_worker_runtime/test_escalation_step.py \
  tests/integration/v3_worker_runtime/test_escalation_terminals.py \
  tests/integration/v3_worker_runtime/test_delivery_outcome_event_fencing.py \
  tests/integration/v3_worker_runtime/test_delivery_outcome_events.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/worker-runtime.xml"

# Current Queue selection/read truth must stay coherent end-to-end: CallNext
# serialization, staff recall gates, customer position and Day Board projection
# all describe the same eligible waiting population on the accepted schema head.
uv run pytest \
  tests/integration/v3_first_vertical/test_business_and_queue.py::test_concurrent_call_next_never_returns_same_entry \
  tests/integration/v3_first_vertical/test_staff_recall_projection.py \
  tests/integration/v3_first_vertical/test_customer_queue_position_triage.py \
  tests/integration/v3_first_vertical/test_day_board_recall_projection.py \
  tests/integration/v3_first_vertical/test_day_board_queue_ambiguity.py \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/queue-current-read-truth.xml"

# S0b party registry proofs are current product truth. Keep the cédula race,
# confirm monotonicity, verification guard and shared-phone multi-match
# evidence on the accepted migration head so tenancy registry guarantees
# cannot regress silently.
uv run pytest \
  tests/integration/s0b_party_registry \
  -q -m postgres --tb=short --durations=20 \
  --junitxml="$ARTIFACT_DIR/s0b-party-registry.xml"

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

# A proof-map entry counts only when its test actually ran in this gate. This
# prevents dormant legacy files from silently satisfying current guarantees.
uv run python scripts/ci/validate_current_proof_execution.py \
  --junit-dir "$ARTIFACT_DIR" \
  --output "$ARTIFACT_DIR/proof-execution.json"
