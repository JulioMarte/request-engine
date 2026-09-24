from datetime import UTC, datetime

from request_engine.modules.platform_configuration.application.readiness import (
    PlatformDeploymentReadinessFacts,
    PlatformReadiness,
    apply_deployment_readiness,
)


def _readiness(source: str = "none") -> PlatformReadiness:
    return PlatformReadiness(
        managed_smtp_source=source,
        smtp_active_revision=None,
        smtp_last_validated_at=datetime.now(UTC),
        smtp_last_provider_test_outcome=None,
        smtp_last_provider_test_at=None,
        smtp_secret_configured=False,
    )


def test_deployment_readiness_reports_fence_store_and_bootstrap_delivery() -> None:
    merged = apply_deployment_readiness(
        _readiness(),
        PlatformDeploymentReadinessFacts(
            clone_fence="fenced",
            secret_store="configured",
            bootstrap_recovery_delivery_configured=True,
        ),
    )

    assert merged.clone_fence == "fenced"
    assert merged.secret_store == "configured"
    assert merged.recovery_delivery_source == "bootstrap"
    assert merged.oidc == "optional"


def test_managed_delivery_takes_precedence_over_bootstrap_fallback() -> None:
    merged = apply_deployment_readiness(
        _readiness("managed"),
        PlatformDeploymentReadinessFacts(
            clone_fence="open",
            secret_store="configured",
            bootstrap_recovery_delivery_configured=True,
        ),
    )

    assert merged.recovery_delivery_source == "managed"
    assert merged.clone_fence == "open"


def test_unconfigured_delivery_is_reported_without_fabricating_readiness() -> None:
    merged = apply_deployment_readiness(
        _readiness(),
        PlatformDeploymentReadinessFacts(
            clone_fence="fenced",
            secret_store="unconfigured",
            bootstrap_recovery_delivery_configured=False,
        ),
    )

    assert merged.recovery_delivery_source == "unconfigured"
    assert merged.secret_store == "unconfigured"
    assert merged.backup_evidence == "unknown"
    assert merged.restore_drill == "unknown"
