from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "operations" / "p7_production_certification.py"
_SPEC = importlib.util.spec_from_file_location("p7_production_certification", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)

NOW = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    openbao = _write(
        tmp_path / "openbao.json",
        {
            "schema": "request-engine/openbao-operational-acceptance/v1",
            "outcome": "accepted",
            "completed_at": "2026-09-27T02:00:00+00:00",
            "topology_reference": "prod-raft-v1",
            "target": {"address": "https://openbao.internal:8200"},
            "revocation_verified": True,
            "exactly_one_cas_winner": True,
            "winner_value_resolution_verified": True,
            "secret_value_persisted_in_evidence": False,
        },
    )
    smtp = _write(
        tmp_path / "smtp.json",
        {
            "schema": "request-engine/smtp-production-acceptance/v1",
            "outcome": "accepted",
            "completed_at": "2026-09-27T02:10:00+00:00",
            "authenticated": True,
            "credentials_persisted": False,
            "security": "starttls",
            "dns_addresses": ["203.0.113.10"],
            "validation": {"status": "valid", "detail_code": "smtp_valid"},
            "smtp_submission": {"outcome": "delivered", "detail_code": "smtp_test_delivered"},
            "delivery_evidence_reference": "mailbox-audit-42",
            "throttling_evidence_reference": "provider-ticket-43",
        },
    )
    recovery = _write(
        tmp_path / "recovery.json",
        {
            "schema": "request-engine/recovery-certification/v1",
            "outcome": "accepted",
            "service_recovered_at": "2026-09-27T02:20:00+00:00",
            "observed_rpo_seconds": 120.0,
            "observed_rto_seconds": 300.0,
            "accepted_max_rpo_seconds": 300.0,
            "accepted_max_rto_seconds": 600.0,
        },
    )
    return openbao, smtp, recovery


def test_certification_accepts_complete_real_evidence(tmp_path: Path) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    output = tmp_path / "certification.json"
    result = module.certify(
        openbao_path=openbao,
        smtp_path=smtp,
        recovery_path=recovery,
        expected_openbao_topology="prod-raft-v1",
        max_evidence_age_hours=24,
        output=output,
        now=NOW,
    )
    assert result["outcome"] == "accepted"
    assert result["observed_rpo_seconds"] == 120.0
    assert output.exists()
    assert all(len(item["sha256"]) == 64 for item in result["evidence"].values())


def test_certification_rejects_wrong_openbao_topology(tmp_path: Path) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    with pytest.raises(module.CertificationError, match="production topology"):
        module.certify(
            openbao_path=openbao,
            smtp_path=smtp,
            recovery_path=recovery,
            expected_openbao_topology="different-prod-topology",
            max_evidence_age_hours=24,
            now=NOW,
        )


def test_certification_requires_operator_accepted_rpo_rto(tmp_path: Path) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    value = json.loads(recovery.read_text(encoding="utf-8"))
    value["accepted_max_rto_seconds"] = None
    _write(recovery, value)
    with pytest.raises(module.CertificationError, match="operator-accepted RPO/RTO"):
        module.certify(
            openbao_path=openbao,
            smtp_path=smtp,
            recovery_path=recovery,
            expected_openbao_topology="prod-raft-v1",
            max_evidence_age_hours=24,
            now=NOW,
        )


def test_certification_rejects_stale_evidence(tmp_path: Path) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    with pytest.raises(module.CertificationError, match="older than"):
        module.certify(
            openbao_path=openbao,
            smtp_path=smtp,
            recovery_path=recovery,
            expected_openbao_topology="prod-raft-v1",
            max_evidence_age_hours=0.5,
            now=NOW,
        )


def test_certification_rejects_smtp_without_submission_proof(tmp_path: Path) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    value = json.loads(smtp.read_text(encoding="utf-8"))
    value["smtp_submission"] = {"outcome": "unknown"}
    _write(smtp, value)
    with pytest.raises(module.CertificationError, match="submission proof"):
        module.certify(
            openbao_path=openbao,
            smtp_path=smtp,
            recovery_path=recovery,
            expected_openbao_topology="prod-raft-v1",
            max_evidence_age_hours=24,
            now=NOW,
        )


def test_certification_rejects_openbao_evidence_that_could_contain_secret_value(
    tmp_path: Path,
) -> None:
    openbao, smtp, recovery = _evidence(tmp_path)
    value = json.loads(openbao.read_text(encoding="utf-8"))
    value["secret_value_persisted_in_evidence"] = True
    _write(openbao, value)
    with pytest.raises(module.CertificationError, match="OpenBao acceptance proof"):
        module.certify(
            openbao_path=openbao,
            smtp_path=smtp,
            recovery_path=recovery,
            expected_openbao_topology="prod-raft-v1",
            max_evidence_age_hours=24,
            now=NOW,
        )
