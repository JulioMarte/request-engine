#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
candidate_dir="${repo_root}/migrations/sql/v3_candidate"

files=(
  "001-foundation.sql"
  "002-schema.sql"
  "003-integrity.sql"
  "004-worker-primitives.sql"
  "005-read-access.sql"
  "006-capacity-hardening.sql"
  "007-contract-convergence.sql"
  "008-tenant-party-authority.sql"
  "009-party-authority-resolution.sql"
  "010-party-authority-linearization.sql"
  "011-idempotency-error-contract.sql"
  "012-waitlist-foundation.sql"
  "013-slot-offer-recovery.sql"
  "014-reservation-lifecycle.sql"
  "015-worker-runtime-hardening.sql"
  "016-provider-event-dead-letter.sql"
  "017-expired-lease-finalization-fence.sql"
  "018-retry-finalization-fence.sql"
  "019-trusted-execution-provenance.sql"
  "020-durable-correlation.sql"
  "021-release-privilege-hardening.sql"
  "022-runtime-table-privilege-contract.sql"
  "023-scheduled-action-cancellation-fence.sql"
  "024-runtime-function-privilege-contract.sql"
  "025-worker-claim-stale-snapshot-fence.sql"
  "026-security-definer-search-path-hardening.sql"
  "027-reservation-access-delivery.sql"
  "028-cross-tenant-shared-capacity.sql"
  "029-cross-tenant-shared-capacity-hardening.sql"
  "030-cross-tenant-slot-offer-integrity-hardening.sql"
  "031-cross-tenant-provenance-hardening.sql"
  "032-cross-tenant-person-capacity-cardinality.sql"
  "033-cross-tenant-runtime-role-classification.sql"
  "034-cross-tenant-slot-offer-terminal-consistency.sql"
  "035-cross-tenant-slot-source-provenance.sql"
  "036-slot-offer-deferred-trigger-privilege-hardening.sql"
)

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=request_engine_v3}"
: "${PGUSER:=request_engine}"

export PGHOST PGPORT PGDATABASE PGUSER

for file in "${files[@]}"; do
  echo "==> Applying V3 candidate ${file}"
  psql --set=ON_ERROR_STOP=1 --file="${candidate_dir}/${file}"
done

echo "==> Request Engine V3 PostgreSQL candidate applied successfully"
