from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "recovery_drill_evidence", ROOT / "scripts/operations/recovery_drill_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _evidence() -> dict[str, object]:
    return {
        "schema": "request-engine/recovery-drill/v1",
        "bundle_sha256": "a" * 64,
        "backup_completed_at": "2026-09-26T20:00:00+00:00",
        "failure_declared_at": "2026-09-26T20:30:00+00:00",
        "service_recovered_at": "2026-09-26T20:45:00+00:00",
        "proofs": {
            name: True
            for name in (
                "postgres_restored_from_bundle",
                "openbao_restored_from_bundle",
                "bundle_integrity_verified",
                "off_host_copy_retrieved",
                "clean_environment",
                "outbound_fenced_during_restore",
                "clone_side_effects_blocked",
                "request_engine_reads_verified",
                "governed_secret_resolution_verified",
                "platform_owner_offline_recovery_with_openbao_down",
                "platform_owner_offline_recovery_with_smtp_down",
                "old_password_rejected",
                "old_sessions_rejected",
                "recovery_code_reuse_rejected",
                "setup_remained_closed",
            )
        },
    }


def _write(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_certification_measures_observed_rpo_and_rto(tmp_path: Path) -> None:
    result = module.certify(_write(tmp_path, _evidence()), None)
    assert result["outcome"] == "accepted"
    assert result["observed_rpo_seconds"] == 1800.0
    assert result["observed_rto_seconds"] == 900.0


def test_certification_rejects_missing_real_proof(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["proofs"]["off_host_copy_retrieved"] = False  # type: ignore[index]
    with pytest.raises(module.EvidenceError, match="off_host_copy_retrieved"):
        module.certify(_write(tmp_path, evidence), None)


def test_certification_rejects_impossible_timeline(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["backup_completed_at"] = "2026-09-26T21:00:00+00:00"
    with pytest.raises(module.EvidenceError, match="after failure"):
        module.certify(_write(tmp_path, evidence), None)


def test_certification_enforces_operator_selected_rpo_rto(tmp_path: Path) -> None:
    source = _write(tmp_path, _evidence())

    result = module.certify(
        source,
        None,
        max_rpo_seconds=1800.0,
        max_rto_seconds=900.0,
    )

    assert result["accepted_max_rpo_seconds"] == 1800.0
    assert result["accepted_max_rto_seconds"] == 900.0


@pytest.mark.parametrize(
    ("field", "limit", "message"),
    (
        ("max_rpo_seconds", 1799.0, "observed RPO"),
        ("max_rto_seconds", 899.0, "observed RTO"),
    ),
)
def test_certification_rejects_exceeded_recovery_objective(
    tmp_path: Path,
    field: str,
    limit: float,
    message: str,
) -> None:
    kwargs = {field: limit}
    with pytest.raises(module.EvidenceError, match=message):
        module.certify(_write(tmp_path, _evidence()), None, **kwargs)


@pytest.mark.parametrize("field", ["max_rpo_seconds", "max_rto_seconds"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_drill_rejects_non_finite_or_boolean_objectives(
    tmp_path: Path, field: str, value: float
) -> None:
    output = tmp_path / "certification.json"
    with pytest.raises(module.EvidenceError, match="finite non-negative number"):
        module.certify(_write(tmp_path, _evidence()), output, **{field: value})
    assert not output.exists()
