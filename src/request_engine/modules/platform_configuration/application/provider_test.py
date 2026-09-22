from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationRevision,
    PlatformConfigurationInvalid,
    PlatformConfigurationProviderInvalid,
    PlatformProviderValidationFailed,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderTestOutcome,
    ProviderTestResult,
    SmtpProviderTester,
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


class ProviderSecretReference(Protocol):
    secret_id: UUID
    purpose: str
    backend: str
    backend_version: int
    status: str
    revision: int


class ProviderSecretResolver(Protocol):
    async def resolve(
        self,
        actor: PlatformActorContext,
        *,
        binding_id: UUID,
        capability_key: str,
    ) -> ProviderSecretReference: ...


class ProviderTestRecorder(Protocol):
    async def record(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        expected_binding_revision: int | None,
        expected_backend_version: int | None,
        outcome: str,
        detail_code: str,
        idempotency_key: str,
        destination: str,
    ) -> UUID: ...


@dataclass(frozen=True, slots=True)
class PlatformProviderTestResult:
    fact_id: UUID
    outcome: ProviderTestOutcome
    detail_code: str


class PlatformProviderTestService:
    def __init__(
        self,
        *,
        reader: ProviderCandidateReader,
        secret_resolver: ProviderSecretResolver,
        secret_store: PlatformSecretStore | None,
        tester: SmtpProviderTester,
        recorder: ProviderTestRecorder,
    ) -> None:
        self._reader = reader
        self._secret_resolver = secret_resolver
        self._secret_store = secret_store
        self._tester = tester
        self._recorder = recorder

    async def test(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        destination: str,
        idempotency_key: str,
    ) -> PlatformProviderTestResult:
        candidate = await self._reader.get(
            actor,
            configuration_kind=configuration_kind,
            revision=revision,
            capability_key="platform.provider.test",
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
                capability_key="platform.provider.test",
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

        observed: ProviderTestResult = await self._tester.test(
            smtp,
            password=password,
            destination=destination,
            idempotency_key=idempotency_key,
        )
        fact_id = await self._recorder.record(
            actor,
            configuration_kind=configuration_kind,
            revision=revision,
            expected_binding_revision=binding_revision,
            expected_backend_version=backend_version,
            outcome=observed.outcome.value,
            detail_code=observed.detail_code,
            idempotency_key=idempotency_key,
            destination=destination,
        )
        return PlatformProviderTestResult(
            fact_id=fact_id,
            outcome=observed.outcome,
            detail_code=observed.detail_code,
        )
