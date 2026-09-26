from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationMutationResult,
    ConfigurationRevision,
    PlatformConfigurationProviderInvalid,
    PlatformConfigurationReader,
    PlatformConfigurationService,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.oidc import (
    OIDC_CONFIGURATION_KIND,
    parse_oidc_configuration,
)
from request_engine.modules.platform_configuration.application.provider_secrets import (
    ProviderSecretResolver,
    ResolvedProviderSecret,
)
from request_engine.modules.platform_configuration.application.recovery_policy import (
    RECOVERY_POLICY_CONFIGURATION_KIND,
    parse_recovery_policy,
)
from request_engine.modules.platform_configuration.application.smtp import (
    SMTP_CONFIGURATION_KIND,
    SmtpConfigurationValidator,
    parse_smtp_configuration,
)
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.secrets.platform_store import PlatformSecretStore


class PlatformProviderValidationSecretDrift(RuntimeError):
    pass


class PlatformProviderValidationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderValidationEvidence:
    configuration_revision_id: UUID
    binding_id: UUID | None
    binding_revision: int | None
    backend_version: int | None


class ProviderValidationPort(Protocol):
    async def validate(
        self,
        candidate: ConfigurationRevision,
        *,
        secret: bytes | None,
    ) -> None: ...


class PlatformProviderValidationService:
    """Validate provider candidates outside PostgreSQL authority locks.

    The candidate is read first, provider/network I/O happens without an
    authoritative lock, and the final DB command commits only if the exact
    candidate and secret binding/backend versions are still current.
    """

    def __init__(
        self,
        *,
        reader: PlatformConfigurationReader,
        commands: PlatformConfigurationService,
        secret_resolver: ProviderSecretResolver,
        secret_store: PlatformSecretStore | None,
        smtp_validator: SmtpConfigurationValidator,
    ) -> None:
        self._reader = reader
        self._commands = commands
        self._secret_resolver = secret_resolver
        self._secret_store = secret_store
        self._smtp_validator = smtp_validator

    async def validate(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        idempotency_key: str,
    ) -> ConfigurationMutationResult:
        candidate = await self._reader.get(
            actor,
            configuration_kind=configuration_kind,
            revision=revision,
            capability_key="platform.configuration.validate",
        )
        if candidate.state not in {"draft", "validated"}:
            raise PlatformConfigurationProviderInvalid(
                "Only draft or validated configuration can be validated"
            )

        if configuration_kind == SMTP_CONFIGURATION_KIND:
            evidence = await self._validate_smtp(candidate)
        elif configuration_kind == RECOVERY_POLICY_CONFIGURATION_KIND:
            evidence = self._validate_recovery_policy(candidate)
        elif configuration_kind == OIDC_CONFIGURATION_KIND:
            evidence = self._validate_oidc(candidate)
        else:
            raise PlatformConfigurationProviderInvalid(
                f"No provider validator is registered for {configuration_kind}"
            )

        return await self._commands.validate(
            actor,
            ValidateConfiguration(
                configuration_kind=configuration_kind,
                revision=revision,
                expected_revision=revision,
                expected_binding_revision=evidence.binding_revision,
                expected_backend_version=evidence.backend_version,
                idempotency_key=idempotency_key,
            ),
        )

    def _validate_recovery_policy(
        self,
        candidate: ConfigurationRevision,
    ) -> ProviderValidationEvidence:
        if candidate.secret_binding_id is not None:
            raise PlatformConfigurationProviderInvalid(
                "operations.recovery_policy must not reference a secret binding"
            )
        parse_recovery_policy(
            candidate.configuration,
            provider_kind=candidate.provider_kind,
        )
        return ProviderValidationEvidence(
            configuration_revision_id=candidate.configuration_revision_id,
            binding_id=None,
            binding_revision=None,
            backend_version=None,
        )

    def _validate_oidc(
        self,
        candidate: ConfigurationRevision,
    ) -> ProviderValidationEvidence:
        if candidate.secret_binding_id is not None:
            raise PlatformConfigurationProviderInvalid(
                "identity.oidc must not reference a secret binding"
            )
        parse_oidc_configuration(
            candidate.configuration,
            provider_kind=candidate.provider_kind,
        )
        return ProviderValidationEvidence(
            configuration_revision_id=candidate.configuration_revision_id,
            binding_id=None,
            binding_revision=None,
            backend_version=None,
        )

    async def _validate_smtp(
        self,
        candidate: ConfigurationRevision,
    ) -> ProviderValidationEvidence:
        config = parse_smtp_configuration(candidate.configuration)
        if candidate.secret_binding_id is None:
            if config.username is not None:
                raise PlatformConfigurationProviderInvalid(
                    "SMTP username requires a governed secret binding"
                )
            await self._smtp_validator.validate(config, password=None)
            return ProviderValidationEvidence(
                configuration_revision_id=candidate.configuration_revision_id,
                binding_id=None,
                binding_revision=None,
                backend_version=None,
            )
        if self._secret_store is None:
            raise PlatformProviderValidationUnavailable(
                "Provider validation requires a configured secret store"
            )

        resolved: ResolvedProviderSecret = await self._secret_resolver.resolve(
            candidate.secret_binding_id,
            expected_purpose="email.smtp.password",
            capability_key="platform.configuration.validate",
        )
        try:
            await self._smtp_validator.validate(config, password=resolved.value)
        finally:
            resolved.destroy()
        return ProviderValidationEvidence(
            configuration_revision_id=candidate.configuration_revision_id,
            binding_id=candidate.secret_binding_id,
            binding_revision=resolved.binding_revision,
            backend_version=resolved.backend_version,
        )
