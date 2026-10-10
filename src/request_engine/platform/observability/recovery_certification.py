"""Read a protected, operator-accepted recovery certification as bounded gauges."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

MAX_CERTIFICATION_BYTES = 64 * 1024
REQUIRED_PROOFS = frozenset(
    {
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
    }
)


@dataclass(frozen=True, slots=True)
class RecoveryEvidenceMetrics:
    backup_verified: float
    restore_drill_verified: float
    backup_age_seconds: float | None
    restore_drill_age_seconds: float | None


UNKNOWN_RECOVERY_EVIDENCE = RecoveryEvidenceMetrics(0.0, 0.0, None, None)


def _timestamp(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp timezone missing")
    return parsed.astimezone(UTC)


def _read_protected(path: Path) -> bytes:
    if not path.is_absolute():
        raise ValueError("certification path must be absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("certification is not a regular file")
        if metadata.st_size > MAX_CERTIFICATION_BYTES:
            raise ValueError("certification exceeds size limit")
        if metadata.st_mode & (
            stat.S_IWUSR
            | stat.S_IWGRP
            | stat.S_IWOTH
            | stat.S_IROTH
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH
        ):
            raise ValueError("certification mode is not protected")
        if metadata.st_mode & stat.S_IRGRP and metadata.st_gid != os.getegid():
            raise ValueError("certification group does not match process group")
        if metadata.st_uid not in (0, os.geteuid()):
            raise ValueError("unexpected certification owner")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(MAX_CERTIFICATION_BYTES + 1)
        if len(content) > MAX_CERTIFICATION_BYTES:
            raise ValueError("certification exceeds size limit")
        return content
    finally:
        os.close(descriptor)


def load_recovery_evidence(
    path: Path | None,
    *,
    now: datetime | None = None,
) -> RecoveryEvidenceMetrics:
    """Return fail-unknown gauges; never expose source content or identifiers."""
    if path is None:
        return UNKNOWN_RECOVERY_EVIDENCE
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        return UNKNOWN_RECOVERY_EVIDENCE
    instant = instant.astimezone(UTC)
    try:
        parsed: object = json.loads(_read_protected(path))
        if not isinstance(parsed, dict):
            return UNKNOWN_RECOVERY_EVIDENCE
        raw = cast(dict[str, object], parsed)
        if (
            raw.get("schema") != "request-engine/recovery-certification/v1"
            or raw.get("outcome") != "accepted"
        ):
            return UNKNOWN_RECOVERY_EVIDENCE
        digest = raw.get("bundle_sha256")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
            return UNKNOWN_RECOVERY_EVIDENCE
        proofs = raw.get("required_proofs")
        if not isinstance(proofs, list):
            return UNKNOWN_RECOVERY_EVIDENCE
        proof_values = cast(list[object], proofs)
        proof_strings = [proof for proof in proof_values if isinstance(proof, str)]
        if (
            len(proof_strings) != len(REQUIRED_PROOFS)
            or frozenset(proof_strings) != REQUIRED_PROOFS
        ):
            return UNKNOWN_RECOVERY_EVIDENCE
        backup_completed = _timestamp(raw.get("backup_completed_at"))
        service_recovered = _timestamp(raw.get("service_recovered_at"))
        if backup_completed > service_recovered or service_recovered > instant:
            return UNKNOWN_RECOVERY_EVIDENCE
        return RecoveryEvidenceMetrics(
            backup_verified=1.0,
            restore_drill_verified=1.0,
            backup_age_seconds=(instant - backup_completed).total_seconds(),
            restore_drill_age_seconds=(instant - service_recovered).total_seconds(),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return UNKNOWN_RECOVERY_EVIDENCE
