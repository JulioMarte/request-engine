from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Final, cast

_PRESET_NAME: Final = "coolify_balanced_v1"
_ALLOWED_FREQUENCIES: Final = frozenset(
    {"every_minute", "hourly", "daily", "weekly", "monthly", "yearly"}
)
_CRON_FIELD: Final = re.compile(r"^[0-9*/?,\-]+$")


@dataclass(frozen=True, slots=True)
class PostgresBackupPolicy:
    frequency: str
    local_retention_days: int
    s3_retention_days: int
    timeout_seconds: int
    require_s3: bool


@dataclass(frozen=True, slots=True)
class OpenBaoSnapshotPolicy:
    frequency: str
    local_retention_days: int
    offsite_retention_days: int
    require_offsite: bool


@dataclass(frozen=True, slots=True)
class RecoverySetPolicy:
    max_component_skew_minutes: int
    restore_drill_interval_days: int
    target_rpo_minutes: int
    target_rto_minutes: int
    require_clone_fence: bool


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    postgres: PostgresBackupPolicy
    openbao: OpenBaoSnapshotPolicy
    recovery_set: RecoverySetPolicy


def recovery_policy_preset_name() -> str:
    return _PRESET_NAME


def recovery_policy_preset() -> RecoveryPolicy:
    return RecoveryPolicy(
        postgres=PostgresBackupPolicy(
            frequency="hourly",
            local_retention_days=7,
            s3_retention_days=30,
            timeout_seconds=3600,
            require_s3=True,
        ),
        openbao=OpenBaoSnapshotPolicy(
            frequency="5 * * * *",
            local_retention_days=7,
            offsite_retention_days=30,
            require_offsite=True,
        ),
        recovery_set=RecoverySetPolicy(
            max_component_skew_minutes=15,
            restore_drill_interval_days=30,
            target_rpo_minutes=60,
            target_rto_minutes=120,
            require_clone_fence=True,
        ),
    )


def recovery_policy_preset_payload() -> dict[str, object]:
    return asdict(recovery_policy_preset())


def parse_recovery_policy(payload: dict[str, object]) -> RecoveryPolicy:
    _exact_keys(payload, {"postgres", "openbao", "recovery_set"}, "recovery policy")
    postgres = _mapping(payload.get("postgres"), "postgres")
    openbao = _mapping(payload.get("openbao"), "openbao")
    recovery_set = _mapping(payload.get("recovery_set"), "recovery_set")

    _exact_keys(
        postgres,
        {"frequency", "local_retention_days", "s3_retention_days", "timeout_seconds", "require_s3"},
        "postgres",
    )
    _exact_keys(
        openbao,
        {"frequency", "local_retention_days", "offsite_retention_days", "require_offsite"},
        "openbao",
    )
    _exact_keys(
        recovery_set,
        {
            "max_component_skew_minutes",
            "restore_drill_interval_days",
            "target_rpo_minutes",
            "target_rto_minutes",
            "require_clone_fence",
        },
        "recovery_set",
    )

    return RecoveryPolicy(
        postgres=PostgresBackupPolicy(
            frequency=_frequency(postgres.get("frequency"), "postgres.frequency"),
            local_retention_days=_integer_between(
                postgres.get("local_retention_days"), "postgres.local_retention_days", 1, 3650
            ),
            s3_retention_days=_integer_between(
                postgres.get("s3_retention_days"), "postgres.s3_retention_days", 1, 3650
            ),
            timeout_seconds=_integer_between(
                postgres.get("timeout_seconds"), "postgres.timeout_seconds", 60, 36000
            ),
            require_s3=_boolean(postgres.get("require_s3"), "postgres.require_s3"),
        ),
        openbao=OpenBaoSnapshotPolicy(
            frequency=_frequency(openbao.get("frequency"), "openbao.frequency"),
            local_retention_days=_integer_between(
                openbao.get("local_retention_days"), "openbao.local_retention_days", 1, 3650
            ),
            offsite_retention_days=_integer_between(
                openbao.get("offsite_retention_days"), "openbao.offsite_retention_days", 1, 3650
            ),
            require_offsite=_boolean(openbao.get("require_offsite"), "openbao.require_offsite"),
        ),
        recovery_set=RecoverySetPolicy(
            max_component_skew_minutes=_integer_between(
                recovery_set.get("max_component_skew_minutes"),
                "recovery_set.max_component_skew_minutes",
                0,
                1440,
            ),
            restore_drill_interval_days=_integer_between(
                recovery_set.get("restore_drill_interval_days"),
                "recovery_set.restore_drill_interval_days",
                1,
                365,
            ),
            target_rpo_minutes=_integer_between(
                recovery_set.get("target_rpo_minutes"), "recovery_set.target_rpo_minutes", 1, 10080
            ),
            target_rto_minutes=_integer_between(
                recovery_set.get("target_rto_minutes"), "recovery_set.target_rto_minutes", 1, 10080
            ),
            require_clone_fence=_boolean(
                recovery_set.get("require_clone_fence"), "recovery_set.require_clone_fence"
            ),
        ),
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    mapping = cast(dict[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _exact_keys(payload: dict[str, object], expected: set[str], name: str) -> None:
    missing = expected - set(payload)
    unknown = set(payload) - expected
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} has unsupported fields: {sorted(unknown)}")


def _frequency(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a named frequency or five-field cron expression")
    normalized = " ".join(value.strip().split())
    if normalized in _ALLOWED_FREQUENCIES:
        return normalized
    fields = normalized.split(" ")
    if len(fields) == 5 and all(_CRON_FIELD.fullmatch(field) for field in fields):
        return normalized
    raise ValueError(f"{name} must be a named frequency or five-field cron expression")


def _integer_between(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
