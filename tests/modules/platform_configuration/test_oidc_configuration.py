from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationMutationResult,
    ConfigurationRevision,
    PlatformConfigurationProviderInvalid,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.oidc import (
    OIDC_CONFIGURATION_KIND,
    OidcProviderConfiguration,
    OidcValidationResult,
    OidcValidationStatus,
    parse_oidc_configuration,
)
from request_engine.modules.platform_configuration.application.provider_secrets import (
    ProviderSecretResolver,
)
from request_engine.modules.platform_configuration.application.provider_validation import (
    PlatformProviderValidationService,
)
from request_engine.modules.platform_configuration.application.smtp import (
    SmtpConfigurationValidator,
)
from request_engine.platform.security.platform_context import PlatformActorContext


class _Reader:
    def __init__(self, candidate: ConfigurationRevision) -> None:
        self.candidate = candidate

    async def get(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        capability_key: str,
    ) -> ConfigurationRevision:
        del actor, configuration_kind, revision, capability_key
        return self.candidate


class _OidcValidator:
    def __init__(self, status: OidcValidationStatus = OidcValidationStatus.VALID) -> None:
        self.status = status
        self.configuration: OidcProviderConfiguration | None = None

    async def validate(
        self,
        configuration: OidcProviderConfiguration,
    ) -> OidcValidationResult:
        self.configuration = configuration
        return OidcValidationResult(self.status, f"oidc_{self.status.value}")


class _Commands:
    def __init__(self) -> None:
        self.command: ValidateConfiguration | None = None

    async def validate(
        self,
        actor: PlatformActorContext,
        command: ValidateConfiguration,
    ) -> ConfigurationMutationResult:
        del actor
        self.command = command
        return ConfigurationMutationResult(uuid4(), command.revision, "validated")


def _candidate(*, secret_binding: bool = False) -> ConfigurationRevision:
    return ConfigurationRevision(
        configuration_revision_id=uuid4(),
        configuration_kind=OIDC_CONFIGURATION_KIND,
        provider_kind="oidc",
        revision=3,
        configuration={
            "issuer": "https://id.example.com/",
            "jwks_uri": "https://id.example.com/.well-known/jwks.json",
            "audience": "request-engine",
        },
        secret_binding_id=uuid4() if secret_binding else None,
        state="draft",
        created_by_principal_id=uuid4(),
        created_at=datetime.now(UTC),
        validated_at=None,
        activated_at=None,
        disabled_at=None,
    )


def test_oidc_payload_is_typed_and_normalizes_issuer() -> None:
    parsed = parse_oidc_configuration(
        _candidate().configuration,
        provider_kind="oidc",
    )
    assert parsed.issuer == "https://id.example.com"
    assert parsed.audience == "request-engine"


@pytest.mark.parametrize(
    "patch",
    [
        {"issuer": "http://id.example.com"},
        {"jwks_uri": "http://id.example.com/jwks"},
        {"issuer": "https://user:pass@id.example.com"},
        {"issuer": "https://id.example.com/#fragment"},
        {"issuer": "https://id.example.com?tenant=bad"},
        {"issuer": "https://id.example.com\\evil"},
        {"jwks_uri": "https://id.example.com:99999/jwks"},
        {"audience": ""},
        {"client_secret": "must-never-enter-postgres"},
    ],
)
def test_oidc_payload_fails_closed_for_unsafe_or_unknown_fields(
    patch: dict[str, object],
) -> None:
    payload = dict(_candidate().configuration)
    payload.update(patch)
    with pytest.raises(PlatformConfigurationProviderInvalid):
        parse_oidc_configuration(payload, provider_kind="oidc")


@pytest.mark.asyncio
async def test_oidc_revision_validates_without_secret_binding() -> None:
    commands = _Commands()
    service = PlatformProviderValidationService(
        reader=_Reader(_candidate()),
        commands=commands,
        secret_resolver=cast(ProviderSecretResolver, object()),
        secret_store=None,
        smtp_validator=cast(SmtpConfigurationValidator, object()),
        oidc_validator=_OidcValidator(),
    )

    result = await service.validate(
        cast(PlatformActorContext, object()),
        configuration_kind=OIDC_CONFIGURATION_KIND,
        revision=3,
        idempotency_key="oidc-validation",
    )

    assert result.state == "validated"
    assert commands.command is not None
    assert commands.command.expected_binding_revision is None
    assert commands.command.expected_backend_version is None


@pytest.mark.asyncio
async def test_oidc_revision_rejects_secret_binding() -> None:
    service = PlatformProviderValidationService(
        reader=_Reader(_candidate(secret_binding=True)),
        commands=_Commands(),
        secret_resolver=cast(ProviderSecretResolver, object()),
        secret_store=None,
        smtp_validator=cast(SmtpConfigurationValidator, object()),
        oidc_validator=_OidcValidator(),
    )

    with pytest.raises(PlatformConfigurationProviderInvalid):
        await service.validate(
            cast(PlatformActorContext, object()),
            configuration_kind=OIDC_CONFIGURATION_KIND,
            revision=3,
            idempotency_key="oidc-secret-rejected",
        )


@pytest.mark.parametrize(
    "status,expected_exception",
    [
        (OidcValidationStatus.INVALID, PlatformConfigurationProviderInvalid),
    ],
)
@pytest.mark.asyncio
async def test_oidc_provider_validation_rejects_invalid_external_jwks(
    status: OidcValidationStatus,
    expected_exception: type[Exception],
) -> None:
    validator = _OidcValidator(status)
    service = PlatformProviderValidationService(
        reader=_Reader(_candidate()),
        commands=_Commands(),
        secret_resolver=cast(ProviderSecretResolver, object()),
        secret_store=None,
        smtp_validator=cast(SmtpConfigurationValidator, object()),
        oidc_validator=validator,
    )

    with pytest.raises(expected_exception):
        await service.validate(
            cast(PlatformActorContext, object()),
            configuration_kind=OIDC_CONFIGURATION_KIND,
            revision=3,
            idempotency_key="oidc-invalid-jwks",
        )
    assert validator.configuration is not None
