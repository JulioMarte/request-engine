from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlatformReadiness:
    managed_smtp_source: str
    smtp_active_revision: int | None
    smtp_last_validated_at: datetime | None
    smtp_last_provider_test_outcome: str | None
    smtp_last_provider_test_at: datetime | None
    smtp_secret_configured: bool
    backup_evidence: str = "unknown"
    restore_drill: str = "unknown"
    clone_fence: str = "unknown"
    secret_store: str = "unknown"
    recovery_delivery_source: str = "unknown"
    oidc: str = "optional"


@dataclass(frozen=True, slots=True)
class PlatformDeploymentReadinessFacts:
    """Non-authoritative process/deployment facts composed outside PostgreSQL."""

    clone_fence: str = "unknown"
    secret_store: str = "unknown"
    bootstrap_recovery_delivery_configured: bool = False
    oidc: str = "optional"


def apply_deployment_readiness(
    readiness: PlatformReadiness,
    facts: PlatformDeploymentReadinessFacts,
) -> PlatformReadiness:
    """Merge deployment diagnostics without changing durable authorization state."""

    if readiness.managed_smtp_source == "managed":
        recovery_delivery_source = "managed"
    elif facts.bootstrap_recovery_delivery_configured:
        recovery_delivery_source = "bootstrap"
    else:
        recovery_delivery_source = "unconfigured"
    return replace(
        readiness,
        clone_fence=facts.clone_fence,
        secret_store=facts.secret_store,
        recovery_delivery_source=recovery_delivery_source,
        oidc=facts.oidc,
    )
