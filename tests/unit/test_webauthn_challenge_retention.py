import math

import pytest

from request_engine.platform.db.webauthn_challenge_retention import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RETENTION_SECONDS,
    MAX_BATCH_SIZE,
    MAX_RETENTION_SECONDS,
    MIN_RETENTION_SECONDS,
    parse_integer_setting,
    validate_retention_configuration,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def test_retention_configuration_accepts_inclusive_bounds() -> None:
    assert validate_retention_configuration(MIN_RETENTION_SECONDS, 1) == (
        MIN_RETENTION_SECONDS,
        1,
    )
    assert validate_retention_configuration(MAX_RETENTION_SECONDS, MAX_BATCH_SIZE) == (
        MAX_RETENTION_SECONDS,
        MAX_BATCH_SIZE,
    )
    assert validate_retention_configuration(DEFAULT_RETENTION_SECONDS, DEFAULT_BATCH_SIZE) == (
        DEFAULT_RETENTION_SECONDS,
        DEFAULT_BATCH_SIZE,
    )


@pytest.mark.parametrize(
    "retention",
    [True, 1.0, math.nan, math.inf, -math.inf, "604800", None],
)
def test_retention_configuration_rejects_non_exact_integer_seconds(retention: object) -> None:
    with pytest.raises(ValueError, match="retention_seconds must be an integer"):
        validate_retention_configuration(retention, DEFAULT_BATCH_SIZE)


@pytest.mark.parametrize("retention", [MIN_RETENTION_SECONDS - 1, MAX_RETENTION_SECONDS + 1])
def test_retention_configuration_rejects_out_of_policy_retention(retention: int) -> None:
    with pytest.raises(ValueError, match="between 86400 and 7776000"):
        validate_retention_configuration(retention, DEFAULT_BATCH_SIZE)


@pytest.mark.parametrize("batch", [True, 1.0, math.nan, math.inf, "500", None])
def test_retention_configuration_rejects_non_exact_integer_batch(batch: object) -> None:
    with pytest.raises(ValueError, match="batch_size must be an integer"):
        validate_retention_configuration(DEFAULT_RETENTION_SECONDS, batch)


@pytest.mark.parametrize("batch", [0, MAX_BATCH_SIZE + 1])
def test_retention_configuration_rejects_out_of_policy_batch(batch: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        validate_retention_configuration(DEFAULT_RETENTION_SECONDS, batch)


@pytest.mark.parametrize(
    "value", [True, 604800.0, math.nan, math.inf, "NaN", "inf", "1.0", "1e3", ""]
)
def test_deployment_settings_reject_non_decimal_integer_forms(value: object) -> None:
    with pytest.raises(ValueError, match="decimal integer"):
        parse_integer_setting(value, name="retention seconds")
