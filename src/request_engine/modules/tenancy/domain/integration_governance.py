from datetime import UTC, datetime
from enum import StrEnum


class IntegrationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


INTEGRATION_STATUS_TRANSITIONS: dict[IntegrationStatus, frozenset[IntegrationStatus]] = {
    IntegrationStatus.PENDING: frozenset({IntegrationStatus.ACTIVE, IntegrationStatus.REVOKED}),
    IntegrationStatus.ACTIVE: frozenset({IntegrationStatus.SUSPENDED, IntegrationStatus.REVOKED}),
    IntegrationStatus.SUSPENDED: frozenset({IntegrationStatus.ACTIVE, IntegrationStatus.REVOKED}),
    IntegrationStatus.REVOKED: frozenset(),
}


def require_integration_status_transition(
    current: IntegrationStatus,
    target: IntegrationStatus,
) -> None:
    if target not in INTEGRATION_STATUS_TRANSITIONS[current]:
        raise ValueError(f"integration cannot transition from {current.value} to {target.value}")


def integration_transition_capability(target: IntegrationStatus) -> str:
    if target is IntegrationStatus.ACTIVE:
        return "integration.provision"
    if target in {IntegrationStatus.SUSPENDED, IntegrationStatus.REVOKED}:
        return "integration.suspend"
    raise ValueError("target_status must be active, suspended, or revoked")


def integration_credential_expiry(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("credential_expires_at must include a timezone")
    return value.astimezone(UTC)
