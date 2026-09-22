from __future__ import annotations

from typing import Protocol

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationMutationResult,
    ConfigurationRevision,
    PlatformConfigurationInvalid,
    PlatformConfigurationProviderInvalid,
    PlatformProviderValidationFailed,
    ValidateConfiguration,
)
from request_engine.modules.platform_configuration.application.provider_secrets import (
    ProviderSecretResolver,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderValidationStatus,
    SmtpConfigurationValidator,
    parse_smtp_configuration,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)
from request_engine.platform.security.platform_context import PlatformActorContext


class ProviderCandidateReader(Protocol):
    async def get(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        capability_key: str,
    ) -> ConfigurationRevision: ...


class ConfigurationCommands(Protocol):
    async def validate(
        self,
        actor: PlatformActorContext,
        command: ValidateConfiguration,
    ) -> ConfigurationMutationResult: ...


class PlatformProviderValidationService:
    def __init__(
        self,
        *,
        reader: ProviderCandidateReader,
        commands: ConfigurationCommands,
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
        if candidate.configuration_kind != "email.delivery" or candidate.provider_kind != "smtp":
            raise PlatformConfigurationInvalid()

        try:
            smtp = parse_smtp_configuration(candidate.configuration)
        except (TypeError, ValueError) as exc:
            raise PlatformConfigurationProviderInvalid() from exc

        binding_revision: int | None = None
        backend_version: int | None = None
        password: str | None = None

        if smtp.username is not None:
            if candidate.secret_binding_id is None:
                raise PlatformConfigurationProviderInvalid()
            secret = await self._secret_resolver.resolve(
                actor,
                binding_id=candidate.secret_binding_id,
                capability_key="platform.configuration.validate",
            )
            if (
                secret.status != "active"
                or secret.purpose != "email.smtp.password"
                or secret.backend != "openbao"
            ):
                raise PlatformConfigurationProviderInvalid()
            binding_revision = secret.revision
            backend_version = secret.backend_version
            if self._secret_store is None:
                raise PlatformProviderValidationFailed()
            try:
                password = await self._secret_store.resolve(secret_id=secret.secret_id)
            except PlatformSecretNotFound as exc:
                raise PlatformConfigurationProviderInvalid() from exc
            except PlatformSecretStoreUnavailable as exc:
                raise PlatformProviderValidationFailed() from exc
        elif candidate.secret_binding_id is not None:
            raise PlatformConfigurationProviderInvalid()

        result = await self._smtp_validator.validate(smtp, password=password)
        if result.status is ProviderValidationStatus.INVALID:
            raise PlatformConfigurationProviderInvalid(result.detail_code)
        if result.status is ProviderValidationStatus.UNAVAILABLE:
            raise PlatformProviderValidationFailed(result.detail_code)

        return await self._commands.validate(
            actor,
            ValidateConfiguration(
                configuration_kind=configuration_kind,
                revision=revision,
                expected_binding_revision=binding_revision,
                expected_backend_version=backend_version,
                idempotency_key=idempotency_key,
            ),
        )
