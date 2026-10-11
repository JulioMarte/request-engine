"""Validation and publishing helpers for the private operator collector."""

from __future__ import annotations

import threading

from sqlalchemy.engine import URL, make_url

from request_engine.platform.observability.recovery_certification import (
    RecoveryEvidenceMetrics,
)

type MetricValues = dict[str, list[tuple[float, dict[str, str]]]]


def validate_operator_metrics_database_url(value: str) -> URL:
    """Accept only asyncpg PostgreSQL URLs with explicit host and database."""
    try:
        parsed = make_url(value)
    except Exception:
        raise ValueError("invalid operator metrics database URL") from None
    if parsed.drivername != "postgresql+asyncpg" or not parsed.host or not parsed.database:
        raise ValueError("operator metrics database URL must use asyncpg and specify host/database")
    return parsed


def publish_recovery_evidence_metrics(
    values: MetricValues,
    evidence: RecoveryEvidenceMetrics,
    lock: threading.Lock,
) -> None:
    """Publish verification bits and timestamp ages, omitting unknown ages."""
    with lock:
        values["backup_evidence_verified"] = [(evidence.backup_verified, {})]
        values["restore_drill_verified"] = [(evidence.restore_drill_verified, {})]
        values["backup_evidence_age_seconds"] = (
            [] if evidence.backup_age_seconds is None else [(evidence.backup_age_seconds, {})]
        )
        values["restore_drill_evidence_age_seconds"] = (
            []
            if evidence.restore_drill_age_seconds is None
            else [(evidence.restore_drill_age_seconds, {})]
        )
