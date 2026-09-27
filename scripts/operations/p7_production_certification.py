#!/usr/bin/env python3
"""Certify P7 production readiness from real operational evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class CertificationError(RuntimeError):
    pass


def _load(path: Path, *, schema: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CertificationError(f"cannot read evidence: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != schema:
        raise CertificationError(f"unexpected evidence schema: {path}")
    if raw.get("outcome") != "accepted":
        raise CertificationError(f"evidence is not accepted: {path}")
    return raw


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _time(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CertificationError(f"missing timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CertificationError(f"invalid timestamp: {field}") from exc
    if parsed.tzinfo is None:
        raise CertificationError(f"timestamp must include timezone: {field}")
    return parsed.astimezone(UTC)


def _fresh(completed_at: datetime, *, now: datetime, max_age_hours: float, label: str) -> None:
    if completed_at > now + timedelta(minutes=5):
        raise CertificationError(f"{label} evidence timestamp is in the future")
    age = now - completed_at
    if age > timedelta(hours=max_age_hours):
        raise CertificationError(f"{label} evidence is older than {max_age_hours:g} hours")


def certify(
    *,
    openbao_path: Path,
    smtp_path: Path,
    recovery_path: Path,
    expected_openbao_topology: str,
    max_evidence_age_hours: float,
    output: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if max_evidence_age_hours <= 0:
        raise CertificationError("max evidence age must be positive")
    expected_topology = expected_openbao_topology.strip()
    if not expected_topology:
        raise CertificationError("expected OpenBao topology reference is required")

    openbao = _load(openbao_path, schema="request-engine/openbao-operational-acceptance/v1")
    smtp = _load(smtp_path, schema="request-engine/smtp-production-acceptance/v1")
    recovery = _load(recovery_path, schema="request-engine/recovery-certification/v1")

    if openbao.get("topology_reference") != expected_topology:
        raise CertificationError("OpenBao evidence does not match the intended production topology")
    target = openbao.get("target")
    if not isinstance(target, dict) or not target.get("address"):
        raise CertificationError("OpenBao evidence does not identify its target")
    if openbao.get("revocation_verified") is not True or openbao.get("exactly_one_cas_winner") is not True:
        raise CertificationError("OpenBao acceptance proof is incomplete")

    if smtp.get("authenticated") is not True or smtp.get("credentials_persisted") is not False:
        raise CertificationError("SMTP acceptance proof is incomplete")
    if not smtp.get("delivery_evidence_reference") or not smtp.get("throttling_evidence_reference"):
        raise CertificationError("SMTP mailbox/throttling evidence references are required")

    observed_rpo = recovery.get("observed_rpo_seconds")
    observed_rto = recovery.get("observed_rto_seconds")
    max_rpo = recovery.get("accepted_max_rpo_seconds")
    max_rto = recovery.get("accepted_max_rto_seconds")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (observed_rpo, observed_rto, max_rpo, max_rto)):
        raise CertificationError("recovery evidence must include measured and operator-accepted RPO/RTO")
    if observed_rpo > max_rpo or observed_rto > max_rto:
        raise CertificationError("observed RPO/RTO exceeds the accepted production limits")

    reference_now = (now or datetime.now(UTC)).astimezone(UTC)
    openbao_completed = _time(openbao.get("completed_at"), field="openbao.completed_at")
    smtp_completed = _time(smtp.get("completed_at"), field="smtp.completed_at")
    recovery_completed = _time(recovery.get("service_recovered_at"), field="recovery.service_recovered_at")
    _fresh(openbao_completed, now=reference_now, max_age_hours=max_evidence_age_hours, label="OpenBao")
    _fresh(smtp_completed, now=reference_now, max_age_hours=max_evidence_age_hours, label="SMTP")
    _fresh(recovery_completed, now=reference_now, max_age_hours=max_evidence_age_hours, label="recovery")

    result = {
        "schema": "request-engine/p7-production-certification/v1",
        "outcome": "accepted",
        "certified_at": reference_now.isoformat(),
        "openbao_topology_reference": expected_topology,
        "observed_rpo_seconds": observed_rpo,
        "observed_rto_seconds": observed_rto,
        "accepted_max_rpo_seconds": max_rpo,
        "accepted_max_rto_seconds": max_rto,
        "evidence": {
            "openbao": {"path": str(openbao_path), "sha256": _sha256(openbao_path)},
            "smtp": {"path": str(smtp_path), "sha256": _sha256(smtp_path)},
            "recovery": {"path": str(recovery_path), "sha256": _sha256(recovery_path)},
        },
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openbao-evidence", type=Path, required=True)
    parser.add_argument("--smtp-evidence", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path, required=True)
    parser.add_argument("--expected-openbao-topology", required=True)
    parser.add_argument("--max-evidence-age-hours", type=float, default=168.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = certify(
            openbao_path=args.openbao_evidence.resolve(),
            smtp_path=args.smtp_evidence.resolve(),
            recovery_path=args.recovery_evidence.resolve(),
            expected_openbao_topology=args.expected_openbao_topology,
            max_evidence_age_hours=args.max_evidence_age_hours,
            output=None if args.output is None else args.output.resolve(),
        )
    except CertificationError as exc:
        raise SystemExit(f"P7 production certification failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
