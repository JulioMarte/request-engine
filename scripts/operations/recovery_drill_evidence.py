#!/usr/bin/env python3
"""Validate P7 disaster-recovery drill evidence and calculate observed RPO/RTO.

This gate deliberately distinguishes repository tooling from an exercised drill.
It accepts machine-readable facts produced by a real restore run and fails closed
when any P7-K proof is absent. It never invents RPO/RTO values.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


class EvidenceError(RuntimeError):
    pass


MAX_EVIDENCE_BYTES = 64 * 1024


def _read_json(path: Path, label: str) -> Any:
    try:
        with path.open("rb") as evidence_file:
            content = evidence_file.read(MAX_EVIDENCE_BYTES + 1)
    except OSError as exc:
        raise EvidenceError(f"cannot read {label}") from exc
    if len(content) > MAX_EVIDENCE_BYTES:
        raise EvidenceError(f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte limit")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON") from exc


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


def _validate_restore_evidence(
    source: Path,
    reference_value: str,
    bundle_sha: str,
    failure: datetime,
    recovered: datetime,
) -> tuple[Path, datetime, datetime]:
    reference = Path(reference_value)
    if not reference.is_absolute():
        reference = source.parent / reference
    restore_value = _read_json(reference, "referenced restore evidence")
    if not isinstance(restore_value, dict):
        raise EvidenceError("referenced restore evidence must be an object")
    record = cast(dict[str, object], restore_value)
    steps_value = record.get("completed_steps")
    if not isinstance(steps_value, list):
        raise EvidenceError("referenced restore evidence lacks completed restore steps")
    steps_list = cast(list[object], steps_value)
    if not all(isinstance(step, str) for step in steps_list):
        raise EvidenceError("referenced restore evidence lacks completed restore steps")
    steps = cast(list[str], steps_value)
    required_steps = {
        "bundle_integrity_verified",
        "postgres_restore_applied",
        "postgres_owner_acl_topology_applied",
        "openbao_raft_force_restore_applied",
    }
    if not required_steps.issubset(steps):
        raise EvidenceError("referenced restore evidence lacks completed restore steps")

    started = _time(record.get("started_at"), "restore_evidence.started_at")
    completed = _time(record.get("completed_at"), "restore_evidence.completed_at")
    if started < failure:
        raise EvidenceError("restore evidence started before failure_declared_at")
    if completed < started:
        raise EvidenceError("restore evidence completed before it started")
    if completed > recovered:
        raise EvidenceError("restore evidence completed after service_recovered_at")
    if (
        record.get("schema") != "request-engine/restore-evidence/v1"
        or record.get("outcome") != "restore_applied_pending_verification"
        or record.get("bundle_sha256") != bundle_sha.lower()
        or record.get("postgres_topology_preserved") is not True
        or record.get("postgres_owner_acl_topology_applied") is not True
        or record.get("post_restore_verification_required") is not True
        or record.get("outbound_isolation_independently_proven") is not False
    ):
        raise EvidenceError("referenced restore evidence does not match this drill bundle")
    return reference, started, completed


def certify(
    source: Path,
    output: Path | None,
    *,
    max_rpo_seconds: float | None = None,
    max_rto_seconds: float | None = None,
) -> dict[str, Any]:
    raw_value = _read_json(source, "recovery drill evidence")
    if not isinstance(raw_value, dict):
        raise EvidenceError("unsupported recovery drill evidence schema")
    raw = cast(dict[str, object], raw_value)
    if raw.get("schema") != "request-engine/recovery-drill/v1":
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
    proof_map = cast(dict[str, object], proofs)
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
        _yes(proof_map.get(name), f"proofs.{name}")

    bundle_sha = raw.get("bundle_sha256")
    if not isinstance(bundle_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", bundle_sha) is None:
        raise EvidenceError("bundle_sha256 must be a SHA-256 hex digest")

    # These references force the operator to attach the actual restore and
    # off-host retrieval records to the drill packet. They are provenance
    # handles, not machine-verifiable claims of network isolation or storage
    # durability; those require deployment-specific independent evidence.
    for field in (
        "restore_evidence_reference",
        "off_host_retrieval_evidence_reference",
        "outbound_fence_evidence_reference",
    ):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EvidenceError(f"missing evidence reference: {field}")
    restore_reference_value = raw["restore_evidence_reference"]
    if not isinstance(restore_reference_value, str):
        raise EvidenceError("missing evidence reference: restore_evidence_reference")
    restore_reference, restore_started, restore_completed = _validate_restore_evidence(
        source,
        restore_reference_value,
        bundle_sha,
        failure,
        recovered,
    )

    rpo = (failure - backup).total_seconds()
    rto = (recovered - failure).total_seconds()
    for name, value in (
        ("max_rpo_seconds", max_rpo_seconds),
        ("max_rto_seconds", max_rto_seconds),
    ):
        if value is not None:
            try:
                valid = not isinstance(value, bool) and math.isfinite(value) and value >= 0
            except (OverflowError, TypeError):
                valid = False
            if not valid:
                raise EvidenceError(f"{name} must be a finite non-negative number")
    if max_rpo_seconds is not None and rpo > max_rpo_seconds:
        raise EvidenceError(
            f"observed RPO {rpo:.3f}s exceeds accepted maximum {max_rpo_seconds:.3f}s"
        )
    if max_rto_seconds is not None and rto > max_rto_seconds:
        raise EvidenceError(
            f"observed RTO {rto:.3f}s exceeds accepted maximum {max_rto_seconds:.3f}s"
        )
    result = {
        "schema": "request-engine/recovery-certification/v1",
        "outcome": "accepted",
        "source": str(source),
        "bundle_sha256": bundle_sha.lower(),
        "observed_rpo_seconds": rpo,
        "observed_rto_seconds": rto,
        "accepted_max_rpo_seconds": max_rpo_seconds,
        "accepted_max_rto_seconds": max_rto_seconds,
        "backup_completed_at": backup.isoformat(),
        "failure_declared_at": failure.isoformat(),
        "restore_started_at": restore_started.isoformat(),
        "restore_completed_at": restore_completed.isoformat(),
        "service_recovered_at": recovered.isoformat(),
        "required_proofs": list(required),
        "restore_evidence_reference": str(restore_reference.resolve()),
        "off_host_retrieval_evidence_reference": raw["off_host_retrieval_evidence_reference"],
        "outbound_fence_evidence_reference": raw["outbound_fence_evidence_reference"],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rpo-seconds", type=float)
    parser.add_argument("--max-rto-seconds", type=float)
    args = parser.parse_args()
    try:
        output = None if args.output is None else args.output.resolve()
        result = certify(
            args.evidence.resolve(),
            output,
            max_rpo_seconds=args.max_rpo_seconds,
            max_rto_seconds=args.max_rto_seconds,
        )
    except (EvidenceError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"recovery drill certification failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
