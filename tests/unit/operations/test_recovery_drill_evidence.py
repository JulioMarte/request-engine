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
        "restore_evidence_reference": "restore-evidence.json",
        "off_host_retrieval_evidence_reference": "storage-audit-678",
        "outbound_fence_evidence_reference": "network-change-456",
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
    restore = {
        "schema": "request-engine/restore-evidence/v1",
        "outcome": "restore_applied_pending_verification",
        "bundle_sha256": value["bundle_sha256"],
        "postgres_topology_preserved": True,
        "postgres_owner_acl_topology_applied": True,
        "post_restore_verification_required": True,
        "outbound_isolation_independently_proven": False,
        "started_at": "2026-09-26T20:35:00+00:00",
        "completed_at": "2026-09-26T20:40:00+00:00",
        "completed_steps": [
            "bundle_integrity_verified",
            "postgres_restore_applied",
            "postgres_owner_acl_topology_applied",
            "openbao_raft_force_restore_applied",
        ],
    }
    (tmp_path / "restore-evidence.json").write_text(json.dumps(restore), encoding="utf-8")
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_certification_measures_observed_rpo_and_rto(tmp_path: Path) -> None:
    result = module.certify(_write(tmp_path, _evidence()), None)
    assert result["outcome"] == "accepted"
    assert result["observed_rpo_seconds"] == 1800.0
    assert result["observed_rto_seconds"] == 900.0
    assert result["restore_started_at"] == "2026-09-26T20:35:00+00:00"
    assert result["restore_completed_at"] == "2026-09-26T20:40:00+00:00"


def test_certification_rejects_missing_real_proof(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["proofs"]["off_host_copy_retrieved"] = False  # type: ignore[index]
    with pytest.raises(module.EvidenceError, match="off_host_copy_retrieved"):
        module.certify(_write(tmp_path, evidence), None)


@pytest.mark.parametrize("digest", ["+" + "a" * 63, " " + "a" * 63, "a" * 63 + "\n"])
def test_certification_rejects_non_hex_digest_spellings(tmp_path: Path, digest: str) -> None:
    evidence = _evidence()
    evidence["bundle_sha256"] = digest
    with pytest.raises(module.EvidenceError, match="SHA-256 hex digest"):
        module.certify(_write(tmp_path, evidence), None)


def test_certification_bounds_source_evidence_read(tmp_path: Path) -> None:
    source = _write(tmp_path, _evidence())
    source.write_bytes(source.read_bytes() + b" " * module.MAX_EVIDENCE_BYTES)
    with pytest.raises(module.EvidenceError, match="recovery drill evidence exceeds"):
        module.certify(source, None)


def test_certification_bounds_referenced_restore_evidence_read(tmp_path: Path) -> None:
    source = _write(tmp_path, _evidence())
    restore_path = tmp_path / "restore-evidence.json"
    restore_path.write_bytes(restore_path.read_bytes() + b" " * module.MAX_EVIDENCE_BYTES)
    with pytest.raises(module.EvidenceError, match="referenced restore evidence exceeds"):
        module.certify(source, None)


@pytest.mark.parametrize("reference", [False, True])
def test_certification_handles_invalid_utf8_evidence(tmp_path: Path, reference: bool) -> None:
    source = _write(tmp_path, _evidence())
    path = tmp_path / ("restore-evidence.json" if reference else "evidence.json")
    path.write_bytes(b"\xff")
    with pytest.raises(module.EvidenceError, match="not valid UTF-8 JSON"):
        module.certify(source, None)


def test_certification_rejects_restore_evidence_for_another_bundle(tmp_path: Path) -> None:
    evidence = _evidence()
    source = _write(tmp_path, evidence)
    restore = json.loads((tmp_path / "restore-evidence.json").read_text(encoding="utf-8"))
    restore["bundle_sha256"] = "b" * 64
    (tmp_path / "restore-evidence.json").write_text(json.dumps(restore), encoding="utf-8")
    with pytest.raises(module.EvidenceError, match="does not match"):
        module.certify(source, None)


def test_certification_requires_restore_actions_before_recovery(tmp_path: Path) -> None:
    source = _write(tmp_path, _evidence())
    restore = json.loads((tmp_path / "restore-evidence.json").read_text(encoding="utf-8"))
    restore["completed_steps"] = ["bundle_integrity_verified"]
    restore["completed_at"] = "2026-09-26T20:50:00+00:00"
    (tmp_path / "restore-evidence.json").write_text(json.dumps(restore), encoding="utf-8")
    with pytest.raises(module.EvidenceError, match="completed restore steps"):
        module.certify(source, None)


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ("missing", "restore_evidence.started_at"),
        ("before_failure", "started before failure_declared_at"),
        ("reversed", "completed before it started"),
    ),
)
def test_certification_requires_restore_interval_inside_drill_window(
    tmp_path: Path, change: str, message: str
) -> None:
    source = _write(tmp_path, _evidence())
    restore_path = tmp_path / "restore-evidence.json"
    restore = json.loads(restore_path.read_text(encoding="utf-8"))
    if change == "missing":
        restore.pop("started_at")
    elif change == "before_failure":
        restore["started_at"] = "2026-09-26T20:29:59+00:00"
    else:
        restore["started_at"] = "2026-09-26T20:41:00+00:00"
    restore_path.write_text(json.dumps(restore), encoding="utf-8")

    with pytest.raises(module.EvidenceError, match=message):
        module.certify(source, None)


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
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, 10**1000])
def test_drill_rejects_non_finite_or_boolean_objectives(
    tmp_path: Path, field: str, value: float
) -> None:
    output = tmp_path / "certification.json"
    with pytest.raises(module.EvidenceError, match="finite non-negative number"):
        module.certify(_write(tmp_path, _evidence()), output, **{field: value})
    assert not output.exists()
