from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v3_candidate_includes_scheduled_action_hardening() -> None:
    apply_script = (ROOT / "scripts/db/apply_v3_candidate.sh").read_text()
    assert '"012-scheduled-action-hardening.sql"' in apply_script


def test_scheduler_exposes_fenced_lease_renewal() -> None:
    worker = (ROOT / "src/request_engine/platform/scheduling/postgres.py").read_text()
    migration = (
        ROOT / "migrations/sql/v3_candidate/012-scheduled-action-hardening.sql"
    ).read_text()
    assert "async def renew(" in worker
    assert "renew_scheduled_action_lease" in migration
    assert "lease_until > clock_timestamp()" in migration


def test_scheduler_claim_uses_tenant_fair_rounds() -> None:
    migration = (
        ROOT / "migrations/sql/v3_candidate/012-scheduled-action-hardening.sql"
    ).read_text()
    assert "PARTITION BY s.organization_id" in migration
    assert "ORDER BY r.tenant_rank" in migration
