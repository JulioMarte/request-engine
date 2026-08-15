from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_ROOT = REPO_ROOT / "migrations" / "sql" / "v3_candidate"
APPLY_SCRIPT = REPO_ROOT / "scripts" / "db" / "apply_v3_candidate.sh"

EXPECTED_V3_CANDIDATE = [
    "001-foundation.sql",
    "002-schema.sql",
    "003-integrity.sql",
    "004-worker-primitives.sql",
    "005-read-access.sql",
    "006-capacity-hardening.sql",
    "007-contract-convergence.sql",
    "008-tenant-party-authority.sql",
    "009-party-authority-resolution.sql",
    "010-party-authority-linearization.sql",
    "011-idempotency-error-contract.sql",
    "012-waitlist-foundation.sql",
    "013-slot-offer-recovery.sql",
    "014-reservation-lifecycle.sql",
    "015-worker-runtime-hardening.sql",
    "016-provider-event-dead-letter.sql",
    "017-expired-lease-finalization-fence.sql",
    "018-retry-finalization-fence.sql",
    "019-trusted-execution-provenance.sql",
    "020-durable-correlation.sql",
    "021-release-privilege-hardening.sql",
    "022-runtime-table-privilege-contract.sql",
    "023-scheduled-action-cancellation-fence.sql",
    "024-runtime-function-privilege-contract.sql",
]


def test_v3_candidate_files_are_explicit_and_ordered() -> None:
    assert [path.name for path in sorted(CANDIDATE_ROOT.glob("*.sql"))] == EXPECTED_V3_CANDIDATE


def test_v3_apply_script_mentions_every_candidate_once_in_order() -> None:
    script = APPLY_SCRIPT.read_text(encoding="utf-8")
    positions = [script.index(f'"{name}"') for name in EXPECTED_V3_CANDIDATE]

    assert positions == sorted(positions)
    for name in EXPECTED_V3_CANDIDATE:
        assert script.count(f'"{name}"') == 1
