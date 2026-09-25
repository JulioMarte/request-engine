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
    ProviderSecretReference,
    ProviderSecretResolver,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderValidationStatus,
    SmtpConfigurationValidator,
    parse_smtp_configuration,
)
from request_engine.modules.platform_configuration.application.webhook import (
    WebhookConfiguration,
    parse_webhook_configuration,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)
from request_engine.platform.security.appointment_option_keyring import (
    parse_appointment_option_keyring,
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
        appointment_signing_secret_store: PlatformSecretStore | None = None,
        smtp_validator: SmtpConfigurationValidator,
    ) -> None:
        self._reader = reader
        self._commands = commands
        self._secret_resolver = secret_resolver
        self._secret_store = secret_store
        self._appointment_signing_secret_store = appointment_signing_secret_store
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

        binding_revision: int | None
        backend_version: int | None
        if candidate.configuration_kind == "email.delivery" and candidate.provider_kind == "smtp":
            binding_revision, backend_version = await self._validate_smtp(actor, candidate)
        elif (
            candidate.configuration_kind == "communications.webhook"
            and candidate.provider_kind == "webhook"
        ):
            binding_revision, backend_version = await self._validate_webhook(actor, candidate)
        elif (
            candidate.configuration_kind == "security.appointment_option_signing"
            and candidate.provider_kind == "hmac-sha256-keyring"
        ):
            binding_revision, backend_version = await self._validate_appointment_signing(
                actor, candidate
            )
        else:
            raise PlatformConfigurationInvalid()

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

    async def _validate_smtp(
        self,
        actor: PlatformActorContext,
        candidate: ConfigurationRevision,
    ) -> tuple[int | None, int | None]:
        try:
            smtp = parse_smtp_configuration(candidate.configuration)
        except (TypeError, ValueError) as exc:
            raise PlatformConfigurationProviderInvalid() from exc

        secret: ProviderSecretReference | None = None
        password: str | None = None
        if smtp.username is not None:
            secret = await self._validated_secret(
                actor,
                candidate,
                purpose="email.smtp.password",
            )
            password = await self._resolve_secret_value(secret)
        elif candidate.secret_binding_id is not None:
            raise PlatformConfigurationProviderInvalid()

        result = await self._smtp_validator.validate(smtp, password=password)
        if result.status is ProviderValidationStatus.INVALID:
            raise PlatformConfigurationProviderInvalid(result.detail_code)
        if result.status is ProviderValidationStatus.UNAVAILABLE:
            raise PlatformProviderValidationFailed(result.detail_code)

        return _secret_fence(secret)

    async def _validate_webhook(
        self,
        actor: PlatformActorContext,
        candidate: ConfigurationRevision,
    ) -> tuple[int | None, int | None]:
        try:
            webhook = parse_webhook_configuration(candidate.configuration)
        except (TypeError, ValueError) as exc:
            raise PlatformConfigurationProviderInvalid() from exc

        secret: ProviderSecretReference | None = None
        if webhook.auth_header_name is not None:
            secret = await self._validated_secret(
                actor,
                candidate,
                purpose="communications.webhook.auth_header",
            )
            await self._resolve_secret_value(secret)
        elif candidate.secret_binding_id is not None:
            raise PlatformConfigurationProviderInvalid()

        _validate_webhook_transport_contract(webhook)
        return _secret_fence(secret)

    async def _validate_appointment_signing(
        self,
        actor: PlatformActorContext,
        candidate: ConfigurationRevision,
    ) -> tuple[int | None, int | None]:
        if candidate.configuration:
            raise PlatformConfigurationProviderInvalid()
        secret = await self._validated_secret(
            actor,
            candidate,
            purpose="security.appointment_option_signing",
        )
        value = await self._resolve_secret_value(
            secret,
            store=self._appointment_signing_secret_store,
        )
        try:
            parse_appointment_option_keyring(value)
        except ValueError as exc:
            raise PlatformConfigurationProviderInvalid() from exc
        return _secret_fence(secret)

    async def _validated_secret(
        self,
        actor: PlatformActorContext,
        candidate: ConfigurationRevision,
        *,
        purpose: str,
    ) -> ProviderSecretReference:
        if candidate.secret_binding_id is None:
            raise PlatformConfigurationProviderInvalid()
        secret = await self._secret_resolver.resolve(
            actor,
            binding_id=candidate.secret_binding_id,
            capability_key="platform.configuration.validate",
        )
        if secret.status != "active" or secret.purpose != purpose or secret.backend != "openbao":
            raise PlatformConfigurationProviderInvalid()
        return secret

    async def _resolve_secret_value(
        self,
        secret: ProviderSecretReference,
        *,
        store: PlatformSecretStore | None = None,
    ) -> str:
        selected_store = self._secret_store if store is None else store
        if selected_store is None:
            raise PlatformProviderValidationFailed()
        try:
            return await selected_store.resolve(secret_id=secret.secret_id)
        except PlatformSecretNotFound as exc:
            raise PlatformConfigurationProviderInvalid() from exc
        except PlatformSecretStoreUnavailable as exc:
            raise PlatformProviderValidationFailed() from exc


def _secret_fence(secret: ProviderSecretReference | None) -> tuple[int | None, int | None]:
    if secret is None:
        return None, None
    return secret.revision, secret.backend_version


def _validate_webhook_transport_contract(webhook: WebhookConfiguration) -> None:
    # There is no safe generic network probe for a delivery webhook: GET/HEAD
    # semantics are provider-specific and a POST would itself be a side effect.
    # Typed URL/header validation plus secret resolution is therefore the
    # validation boundary. Provider behavior is proved by actual Communications
    # delivery and its existing reconciliation semantics.
    if not webhook.base_url.startswith("https://"):
        raise PlatformConfigurationProviderInvalid()
