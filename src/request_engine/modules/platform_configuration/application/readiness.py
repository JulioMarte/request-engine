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
    oidc: str = "unconfigured"


@dataclass(frozen=True, slots=True)
class PlatformDeploymentReadinessFacts:
    """Non-authoritative process/deployment facts composed outside PostgreSQL."""

    clone_fence: str = "unknown"
    secret_store: str = "unknown"
    bootstrap_recovery_delivery_configured: bool = False
    backup_evidence: str = "unknown"
    restore_drill: str = "unknown"
    oidc: str = "optional"


def apply_deployment_readiness(
    readiness: PlatformReadiness,
    facts: PlatformDeploymentReadinessFacts,
) -> PlatformReadiness:
    """Merge deployment diagnostics without changing durable authorization state.

    PostgreSQL owns whether managed OIDC is configured, healthy, or degraded.
    Deployment policy may classify only the durable ``unconfigured`` state as
    optional. It must never hide an active managed provider or a broken runtime
    projection.
    """

    if readiness.managed_smtp_source == "managed":
        recovery_delivery_source = "managed"
    elif facts.bootstrap_recovery_delivery_configured:
        recovery_delivery_source = "bootstrap"
    else:
        recovery_delivery_source = "unconfigured"

    oidc = facts.oidc if readiness.oidc == "unconfigured" else readiness.oidc
    return replace(
        readiness,
        clone_fence=facts.clone_fence,
        secret_store=facts.secret_store,
        backup_evidence=facts.backup_evidence,
        restore_drill=facts.restore_drill,
        recovery_delivery_source=recovery_delivery_source,
        oidc=oidc,
    )
