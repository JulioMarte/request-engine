import threading

import pytest
from sqlalchemy.engine import URL

from request_engine.platform.observability.operator_metrics import (
    MetricValues,
    publish_recovery_evidence_metrics,
    validate_operator_metrics_database_url,
)
from request_engine.platform.observability.recovery_certification import (
    UNKNOWN_RECOVERY_EVIDENCE,
    RecoveryEvidenceMetrics,
)


def test_database_url_requires_postgresql_asyncpg_and_a_named_database() -> None:
    parsed = validate_operator_metrics_database_url(
        "postgresql+asyncpg://monitor:secret@db.internal/engine"
    )
    assert isinstance(parsed, URL)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host == "db.internal"
    assert parsed.database == "engine"

    for value in (
        "postgresql://monitor:secret@db.internal/engine",
        "postgresql+psycopg://monitor:secret@db.internal/engine",
        "postgresql+asyncpg://monitor:secret@db.internal",
        "not a URL containing secret-value",
    ):
        with pytest.raises(ValueError) as exc_info:
            validate_operator_metrics_database_url(value)
        assert "secret-value" not in str(exc_info.value)


def test_unknown_recovery_evidence_publishes_zero_bits_without_fabricated_age() -> None:
    values: MetricValues = {
        "backup_evidence_verified": [],
        "restore_drill_verified": [],
        "backup_evidence_age_seconds": [],
        "restore_drill_evidence_age_seconds": [],
    }

    publish_recovery_evidence_metrics(values, UNKNOWN_RECOVERY_EVIDENCE, threading.Lock())

    assert values == {
        "backup_evidence_verified": [(0.0, {})],
        "restore_drill_verified": [(0.0, {})],
        "backup_evidence_age_seconds": [],
        "restore_drill_evidence_age_seconds": [],
    }


def test_valid_recovery_ages_are_forwarded_as_numeric_gauges() -> None:
    values: MetricValues = {
        "backup_evidence_verified": [],
        "restore_drill_verified": [],
        "backup_evidence_age_seconds": [],
        "restore_drill_evidence_age_seconds": [],
    }
    evidence = RecoveryEvidenceMetrics(1.0, 1.0, 120.0, 30.0)

    publish_recovery_evidence_metrics(values, evidence, threading.Lock())

    assert values["backup_evidence_verified"] == [(1.0, {})]
    assert values["restore_drill_verified"] == [(1.0, {})]
    assert values["backup_evidence_age_seconds"] == [(120.0, {})]
    assert values["restore_drill_evidence_age_seconds"] == [(30.0, {})]
