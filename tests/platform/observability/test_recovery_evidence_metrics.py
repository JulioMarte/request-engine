import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from request_engine.platform.observability.recovery_certification import (
    REQUIRED_PROOFS,
    UNKNOWN_RECOVERY_EVIDENCE,
    load_recovery_evidence,
)


def _certificate(*, backup: str, recovered: str) -> dict[str, object]:
    return {
        "schema": "request-engine/recovery-certification/v1",
        "outcome": "accepted",
        "bundle_sha256": "a" * 64,
        "backup_completed_at": backup,
        "service_recovered_at": recovered,
        "required_proofs": sorted(REQUIRED_PROOFS),
        "restore_evidence_reference": "/evidence/private-restore.json",
        "off_host_retrieval_evidence_reference": "private-reference",
        "outbound_fence_evidence_reference": "private-reference",
    }


def _write(path: Path, value: object) -> None:
    if path.exists():
        path.chmod(0o600)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o400)


def test_accepted_certificate_yields_timestamp_derived_age_without_exporting_source(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    evidence = _certificate(
        backup=(now - timedelta(days=2)).isoformat(),
        recovered=(now - timedelta(hours=3)).isoformat(),
    )
    path = tmp_path / "certification.json"
    _write(path, evidence)

    result = load_recovery_evidence(path, now=now)

    assert result.backup_verified == 1.0
    assert result.restore_drill_verified == 1.0
    assert result.backup_age_seconds == 2 * 24 * 60 * 60
    assert result.restore_drill_age_seconds == 3 * 60 * 60
    assert "/evidence/private-restore.json" not in repr(result)


def test_missing_malformed_or_unaccepted_certificate_is_unknown_without_age(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    assert load_recovery_evidence(None, now=now) == UNKNOWN_RECOVERY_EVIDENCE

    path = tmp_path / "certification.json"
    path.write_text("{malformed", encoding="utf-8")
    path.chmod(0o400)
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE

    _write(
        path,
        _certificate(
            backup=(now - timedelta(days=2)).isoformat(),
            recovered=(now - timedelta(hours=3)).isoformat(),
        )
        | {"outcome": "pending"},
    )
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE


def test_future_or_malformed_timestamps_never_create_fresh_or_negative_age(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    path = tmp_path / "certification.json"
    _write(
        path,
        _certificate(
            backup=(now + timedelta(minutes=1)).isoformat(),
            recovered=now.isoformat(),
        ),
    )
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE

    _write(
        path,
        _certificate(backup="not-a-date", recovered=now.isoformat()),
    )
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE


def test_unprotected_and_oversized_certificate_inputs_are_unknown(tmp_path: Path) -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    path = tmp_path / "certification.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o444)
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE

    path.chmod(0o600)
    path.write_bytes(b" " * (64 * 1024 + 1))
    path.chmod(0o400)
    assert load_recovery_evidence(path, now=now) == UNKNOWN_RECOVERY_EVIDENCE
