from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast


class RecoveryCertificationInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryCertification:
    reference: str
    bundle_sha256: str
    backup_completed_at: datetime
    service_recovered_at: datetime
    observed_rpo_seconds: float
    observed_rto_seconds: float
    accepted_max_rpo_seconds: float | None
    accepted_max_rto_seconds: float | None

    def backup_age_seconds(self, *, now: datetime) -> float:
        return _age(self.backup_completed_at, now=now)

    def restore_drill_age_seconds(self, *, now: datetime) -> float:
        return _age(self.service_recovered_at, now=now)


def parse_recovery_certification(
    payload: object,
    *,
    reference: str,
) -> RecoveryCertification:
    if not reference.strip():
        raise RecoveryCertificationInvalid("recovery certification reference cannot be blank")
    if not isinstance(payload, dict):
        raise RecoveryCertificationInvalid("recovery certification must be an object")
    data = _mapping(cast("dict[object, object]", payload))
    if data.get("schema") != "request-engine/recovery-certification/v1":
        raise RecoveryCertificationInvalid("unsupported recovery certification schema")
    if data.get("outcome") != "accepted":
        raise RecoveryCertificationInvalid("recovery certification outcome is not accepted")

    bundle_sha = data.get("bundle_sha256")
    if not isinstance(bundle_sha, str) or len(bundle_sha) != 64:
        raise RecoveryCertificationInvalid("bundle_sha256 must be a SHA-256 hex digest")
    try:
        int(bundle_sha, 16)
    except ValueError as exc:
        raise RecoveryCertificationInvalid("bundle_sha256 is not hexadecimal") from exc

    backup_completed_at = _timestamp(data.get("backup_completed_at"), "backup_completed_at")
    service_recovered_at = _timestamp(data.get("service_recovered_at"), "service_recovered_at")
    if service_recovered_at < backup_completed_at:
        raise RecoveryCertificationInvalid("service recovery predates the certified backup")

    observed_rpo = _non_negative_number(data.get("observed_rpo_seconds"), "observed_rpo_seconds")
    observed_rto = _non_negative_number(data.get("observed_rto_seconds"), "observed_rto_seconds")
    max_rpo = _optional_non_negative_number(
        data.get("accepted_max_rpo_seconds"), "accepted_max_rpo_seconds"
    )
    max_rto = _optional_non_negative_number(
        data.get("accepted_max_rto_seconds"), "accepted_max_rto_seconds"
    )
    if max_rpo is not None and observed_rpo > max_rpo:
        raise RecoveryCertificationInvalid("certified RPO exceeds its accepted maximum")
    if max_rto is not None and observed_rto > max_rto:
        raise RecoveryCertificationInvalid("certified RTO exceeds its accepted maximum")

    return RecoveryCertification(
        reference=reference,
        bundle_sha256=bundle_sha.lower(),
        backup_completed_at=backup_completed_at,
        service_recovered_at=service_recovered_at,
        observed_rpo_seconds=observed_rpo,
        observed_rto_seconds=observed_rto,
        accepted_max_rpo_seconds=max_rpo,
        accepted_max_rto_seconds=max_rto,
    )


def _mapping(value: dict[object, object]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryCertificationInvalid(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryCertificationInvalid(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise RecoveryCertificationInvalid(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _non_negative_number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RecoveryCertificationInvalid(f"{field} must be numeric")
    result = float(value)
    if result < 0:
        raise RecoveryCertificationInvalid(f"{field} must be non-negative")
    return result


def _optional_non_negative_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    return _non_negative_number(value, field)


def _age(value: datetime, *, now: datetime) -> float:
    if now.tzinfo is None:
        raise RecoveryCertificationInvalid("age reference time must include a timezone")
    age = (now.astimezone(UTC) - value).total_seconds()
    if age < 0:
        raise RecoveryCertificationInvalid("certification timestamps cannot be in the future")
    return age
