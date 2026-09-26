import pytest

from typing import cast

from request_engine.modules.platform_configuration.application.recovery_policy import (
    parse_recovery_policy,
    recovery_policy_preset,
    recovery_policy_preset_name,
    recovery_policy_preset_payload,
)


def test_coolify_balanced_preset_is_safe_and_editable() -> None:
    policy = recovery_policy_preset()

    assert recovery_policy_preset_name() == "coolify_balanced_v1"
    assert policy.postgres.frequency == "hourly"
    assert policy.postgres.local_retention_days == 7
    assert policy.postgres.s3_retention_days == 30
    assert policy.postgres.require_s3 is True
    assert policy.openbao.frequency == "hourly"
    assert policy.openbao.require_offsite is True
    assert policy.recovery_set.max_component_skew_minutes == 15
    assert policy.recovery_set.restore_drill_interval_days == 30
    assert policy.recovery_set.target_rpo_minutes == 60
    assert policy.recovery_set.target_rto_minutes == 120
    assert policy.recovery_set.require_clone_fence is True


def test_preset_payload_round_trips_through_typed_parser() -> None:
    parsed = parse_recovery_policy(recovery_policy_preset_payload())
    assert parsed == recovery_policy_preset()


def test_recovery_policy_accepts_operator_overrides() -> None:
    payload = recovery_policy_preset_payload()
    postgres = dict(cast(dict[str, object], payload["postgres"]))
    postgres["frequency"] = "daily"
    postgres["local_retention_days"] = 14
    payload["postgres"] = postgres

    recovery_set = dict(cast(dict[str, object], payload["recovery_set"]))
    recovery_set["target_rpo_minutes"] = 240
    recovery_set["target_rto_minutes"] = 360
    payload["recovery_set"] = recovery_set

    parsed = parse_recovery_policy(payload)

    assert parsed.postgres.frequency == "daily"
    assert parsed.postgres.local_retention_days == 14
    assert parsed.recovery_set.target_rpo_minutes == 240
    assert parsed.recovery_set.target_rto_minutes == 360


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("postgres.frequency", "sometimes"),
        ("postgres.local_retention_days", 0),
        ("postgres.timeout_seconds", 59),
        ("openbao.offsite_retention_days", 0),
        ("recovery_set.restore_drill_interval_days", 0),
        ("recovery_set.target_rpo_minutes", 0),
        ("recovery_set.target_rto_minutes", 0),
    ],
)
def test_recovery_policy_rejects_invalid_operational_values(path: str, value: object) -> None:
    payload = recovery_policy_preset_payload()
    section_name, field_name = path.split(".")
    section = dict(cast(dict[str, object], payload[section_name]))
    section[field_name] = value
    payload[section_name] = section

    with pytest.raises(ValueError):
        parse_recovery_policy(payload)


def test_recovery_policy_rejects_embedded_extra_fields() -> None:
    payload = recovery_policy_preset_payload()
    postgres = dict(payload["postgres"])
    postgres["api_token"] = "must-not-live-in-policy"
    payload["postgres"] = postgres

    with pytest.raises(ValueError, match="unsupported"):
        parse_recovery_policy(payload)
