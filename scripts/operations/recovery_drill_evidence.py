#!/usr/bin/env python3
"""Validate P7 disaster-recovery drill evidence and calculate observed RPO/RTO.

This gate deliberately distinguishes repository tooling from an exercised drill.
It accepts machine-readable facts produced by a real restore run and fails closed
when any P7-K proof is absent. It never invents RPO/RTO values.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    pass


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"missing timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"invalid timestamp: {field}") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"timestamp must include timezone: {field}")
    return parsed.astimezone(UTC)


def _yes(value: Any, field: str) -> None:
    if value is not True:
        raise EvidenceError(f"required proof is not true: {field}")


def certify(source: Path, output: Path | None) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "request-engine/recovery-drill/v1":
        raise EvidenceError("unsupported recovery drill evidence schema")

    backup = _time(raw.get("backup_completed_at"), "backup_completed_at")
    failure = _time(raw.get("failure_declared_at"), "failure_declared_at")
    recovered = _time(raw.get("service_recovered_at"), "service_recovered_at")
    if backup > failure:
        raise EvidenceError("backup_completed_at is after failure_declared_at")
    if recovered < failure:
        raise EvidenceError("service_recovered_at is before failure_declared_at")

    proofs = raw.get("proofs")
    if not isinstance(proofs, dict):
        raise EvidenceError("proofs must be an object")
    required = (
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
    for name in required:
        _yes(proofs.get(name), f"proofs.{name}")

    bundle_sha = raw.get("bundle_sha256")
    if not isinstance(bundle_sha, str) or len(bundle_sha) != 64:
        raise EvidenceError("bundle_sha256 must be a SHA-256 hex digest")
    try:
        int(bundle_sha, 16)
    except ValueError as exc:
        raise EvidenceError("bundle_sha256 is not hexadecimal") from exc

    rpo = (failure - backup).total_seconds()
    rto = (recovered - failure).total_seconds()
    result = {
        "schema": "request-engine/recovery-certification/v1",
        "outcome": "accepted",
        "source": str(source),
        "bundle_sha256": bundle_sha.lower(),
        "observed_rpo_seconds": rpo,
        "observed_rto_seconds": rto,
        "backup_completed_at": backup.isoformat(),
        "failure_declared_at": failure.isoformat(),
        "service_recovered_at": recovered.isoformat(),
        "required_proofs": list(required),
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        output = None if args.output is None else args.output.resolve()
        result = certify(args.evidence.resolve(), output)
    except (EvidenceError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"recovery drill certification failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
