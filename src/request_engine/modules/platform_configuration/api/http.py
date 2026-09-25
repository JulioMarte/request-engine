from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from request_engine.modules.platform_configuration.adapters.db.configuration import (
    PostgresPlatformConfigurationCommands,
    PostgresPlatformConfigurationReader,
)
from request_engine.modules.platform_configuration.adapters.db.provider_candidates import (
    PostgresProviderCandidateReader,
)
from request_engine.modules.platform_configuration.adapters.db.provider_secrets import (
    PostgresProviderSecretResolver,
)
from request_engine.modules.platform_configuration.adapters.db.provider_tests import (
    PostgresProviderTestRecorder,
)
from request_engine.modules.platform_configuration.adapters.db.readiness import (
    PostgresPlatformReadinessReader,
)
from request_engine.modules.platform_configuration.adapters.db.secrets import (
    PostgresPlatformSecretMutations,
)
from request_engine.modules.platform_configuration.adapters.smtp import (
    SmtplibConfigurationValidator,
    SmtplibProviderTester,
)
from request_engine.modules.platform_configuration.application.configuration import (
    ActivateConfiguration,
    ConfigurationMutationResult,
    ConfigurationRevision,
    DisableConfiguration,
    PlatformConfigurationConflict,
    PlatformConfigurationError,
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
    PlatformConfigurationProviderInvalid,
    PlatformConfigurationRevisionConflict,
    PlatformProviderValidationFailed,
    SecretBindingMetadata,
    StageConfiguration,
)
from request_engine.modules.platform_configuration.application.provider_test import (
    PlatformProviderTestResult,
    PlatformProviderTestService,
)
from request_engine.modules.platform_configuration.application.provider_validation import (
    PlatformProviderValidationService,
)
from request_engine.modules.platform_configuration.application.readiness import (
    PlatformDeploymentReadinessFacts,
    PlatformReadiness,
    apply_deployment_readiness,
)
from request_engine.modules.platform_configuration.application.secret_administration import (
    PlatformSecretAdministrationService,
)
from request_engine.modules.platform_configuration.application.secrets import (
    CreatePlatformSecret,
    PlatformSecretConflict,
    PlatformSecretNotFound,
    PlatformSecretReconciliationRequired,
    PlatformSecretUnavailable,
    RevokePlatformSecret,
    RotatePlatformSecret,
    RotatePlatformSecretIntent,
    SecretMutationResult,
)
from request_engine.modules.platform_configuration.application.smtp import (
    SmtpConfigurationValidator,
    SmtpProviderTester,
    parse_smtp_configuration,
)
from request_engine.modules.platform_configuration.application.webhook import (
    parse_webhook_configuration,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorBody, ErrorEnvelope, ErrorResolution
from request_engine.platform.secrets.platform_store import PlatformSecretStore
from request_engine.platform.security.appointment_option_keyring import (
    create_appointment_option_keyring,
    rotate_appointment_option_keyring,
    validate_appointment_option_key_id,
)
from request_engine.platform.security.freshness import require_phishing_resistant_authentication
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver

_NativeBearer = Annotated[
    HTTPAuthorizationCredentials | None,
    Security(HTTPBearer(scheme_name="NativeSessionBearer", auto_error=False)),
]
_IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


_SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "credential",
        "credentials",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


class StageConfigurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider_kind: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_.-]+$")
    configuration: dict[str, Any]
    secret_binding_id: UUID | None = None

    @field_validator("configuration")
    @classmethod
    def reject_embedded_secret_material(cls, value: dict[str, Any]) -> dict[str, Any]:
        def inspect(node: object) -> None:
            if isinstance(node, dict):
                mapping = cast("dict[object, object]", node)
                for key, child in mapping.items():
                    normalized = str(key).strip().lower().replace("-", "_")
                    if normalized in _SECRET_FIELD_NAMES:
                        raise ValueError("secret material must use a governed secret binding")
                    inspect(child)
            elif isinstance(node, list):
                for child in cast("list[object]", node):
                    inspect(child)

        inspect(value)
        return value


class ActivateConfigurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_active_revision: int | None = Field(default=None, ge=1)


class CreatePlatformSecretBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    purpose: str = Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_.-]{1,127}$")
    backend: str = Field(default="openbao", pattern=r"^openbao$")
    value: SecretStr = Field(min_length=1)


class RotatePlatformSecretBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_backend_version: int = Field(ge=1)
    value: SecretStr = Field(min_length=1)


class CreateAppointmentSigningKeyringBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key_id: str = Field(min_length=1, max_length=80)

    @field_validator("key_id")
    @classmethod
    def validate_key_id(cls, value: str) -> str:
        return validate_appointment_option_key_id(value)


class RotateAppointmentSigningKeyringBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=1)
    expected_backend_version: int = Field(ge=1)
    new_key_id: str = Field(min_length=1, max_length=80)

    @field_validator("new_key_id")
    @classmethod
    def validate_key_id(cls, value: str) -> str:
        return validate_appointment_option_key_id(value)


class RevokePlatformSecretBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    expected_backend_version: int = Field(ge=1)


class SecretMutationView(BaseModel):
    binding_id: UUID
    revision: int
    backend_version: int
    status: str


class ProviderTestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    destination: str = Field(min_length=3, max_length=320)


class ProviderTestView(BaseModel):
    fact_id: UUID
    outcome: str
    detail_code: str


class ConfigurationMutationView(BaseModel):
    configuration_revision_id: UUID
    revision: int
    state: str


class ConfigurationRevisionView(BaseModel):
    configuration_revision_id: UUID
    configuration_kind: str
    provider_kind: str
    revision: int
    configuration: dict[str, Any]
    secret_binding_id: UUID | None
    state: str
    created_by_principal_id: UUID
    created_at: datetime
    validated_at: datetime | None
    activated_at: datetime | None
    disabled_at: datetime | None


class ConfigurationRevisionListView(BaseModel):
    items: list[ConfigurationRevisionView]


class PlatformReadinessView(BaseModel):
    managed_smtp_source: str
    smtp_active_revision: int | None
    smtp_last_validated_at: datetime | None
    smtp_last_provider_test_outcome: str | None
    smtp_last_provider_test_at: datetime | None
    smtp_secret_configured: bool
    backup_evidence: str
    restore_drill: str
    clone_fence: str
    secret_store: str
    recovery_delivery_source: str
    oidc: str


class SecretBindingMetadataView(BaseModel):
    binding_id: UUID
    purpose: str
    backend: str
    configured: bool = True
    backend_version: int
    revision: int
    last_rotated_at: datetime | None
    status: str
    created_at: datetime
    revoked_at: datetime | None


async def platform_configuration_error_handler(_: Request, exc: Exception) -> JSONResponse:
    errors: dict[type[Exception], tuple[int, str, ErrorResolution]] = {
        PlatformConfigurationForbidden: (
            403,
            "platform_configuration_forbidden",
            ErrorResolution.REQUEST_AUTHORITY,
        ),
        PlatformConfigurationNotFound: (
            404,
            "platform_configuration_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformConfigurationConflict: (
            409,
            "platform_configuration_conflict",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
        PlatformConfigurationRevisionConflict: (
            409,
            "platform_configuration_changed",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
        PlatformConfigurationInvalid: (
            422,
            "platform_configuration_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformSecretConflict: (
            409,
            "platform_secret_conflict",
            ErrorResolution.REFRESH_AND_RETRY,
        ),
        PlatformSecretNotFound: (
            404,
            "platform_secret_not_found",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformSecretUnavailable: (
            503,
            "platform_secret_unavailable",
            ErrorResolution.RETRY_SAME_REQUEST,
        ),
        PlatformSecretReconciliationRequired: (
            409,
            "platform_secret_reconciliation_required",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
        PlatformConfigurationProviderInvalid: (
            422,
            "platform_configuration_provider_invalid",
            ErrorResolution.FIX_REQUEST,
        ),
        PlatformProviderValidationFailed: (
            503,
            "platform_provider_validation_failed",
            ErrorResolution.RETRY_SAME_REQUEST,
        ),
    }
    status_code, code, resolution = errors.get(
        type(exc),
        (
            500,
            "platform_configuration_failed",
            ErrorResolution.OPERATOR_INTERVENTION,
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message="The platform configuration operation could not be accepted.",
                resolution=resolution,
                retryable=False,
            )
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def install_platform_configuration_http(
    app: FastAPI,
    *,
    read_session_factory: SessionFactory,
    write_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
    secret_store: PlatformSecretStore | None = None,
    appointment_signing_secret_store: PlatformSecretStore | None = None,
    smtp_validator: SmtpConfigurationValidator | None = None,
    smtp_tester: SmtpProviderTester | None = None,
    deployment_readiness: PlatformDeploymentReadinessFacts | None = None,
) -> None:
    reader = PostgresPlatformConfigurationReader(read_session_factory)
    readiness_reader = PostgresPlatformReadinessReader(read_session_factory)
    commands = PostgresPlatformConfigurationCommands(write_session_factory)
    secret_mutations = PostgresPlatformSecretMutations(write_session_factory)
    secret_service = (
        None
        if secret_store is None
        else PlatformSecretAdministrationService(
            mutations=secret_mutations,
            store=secret_store,
        )
    )
    appointment_signing_secret_service = (
        None
        if appointment_signing_secret_store is None
        else PlatformSecretAdministrationService(
            mutations=secret_mutations,
            store=appointment_signing_secret_store,
        )
    )
    provider_candidate_reader = PostgresProviderCandidateReader(write_session_factory)
    provider_secret_resolver = PostgresProviderSecretResolver(write_session_factory)
    provider_validation = PlatformProviderValidationService(
        reader=provider_candidate_reader,
        commands=commands,
        secret_resolver=provider_secret_resolver,
        secret_store=secret_store,
        appointment_signing_secret_store=appointment_signing_secret_store,
        smtp_validator=smtp_validator or SmtplibConfigurationValidator(),
    )
    provider_test = PlatformProviderTestService(
        reader=provider_candidate_reader,
        secret_resolver=provider_secret_resolver,
        secret_store=secret_store,
        tester=smtp_tester or SmtplibProviderTester(),
        recorder=PostgresProviderTestRecorder(write_session_factory),
    )
    router = APIRouter(tags=["Platform configuration"])

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    async def list_configurations(
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationRevisionListView:
        rows = await reader.list_revisions(actor)
        return ConfigurationRevisionListView(items=[_revision_view(row) for row in rows])

    async def list_configuration_revisions(
        configuration_kind: str,
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationRevisionListView:
        rows = await reader.list_revisions(actor, configuration_kind)
        return ConfigurationRevisionListView(items=[_revision_view(row) for row in rows])

    async def get_configuration_revision(
        configuration_kind: str,
        revision: int,
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationRevisionView:
        return _revision_view(await reader.get_revision(actor, configuration_kind, revision))

    async def get_platform_readiness(
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> PlatformReadinessView:
        readiness = await readiness_reader.read(actor)
        if deployment_readiness is not None:
            readiness = apply_deployment_readiness(readiness, deployment_readiness)
        return _readiness_view(readiness)

    async def get_secret_binding(
        binding_id: UUID,
        _bearer: _NativeBearer,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretBindingMetadataView:
        return _secret_view(await reader.get_secret_binding(actor, binding_id))

    async def create_secret(
        body: CreatePlatformSecretBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretMutationView:
        require_platform_configuration_step_up(actor)
        if body.purpose == "security.appointment_option_signing":
            raise PlatformConfigurationInvalid()
        if secret_service is None:
            raise PlatformSecretUnavailable()
        result = await secret_service.create(
            actor,
            CreatePlatformSecret(
                purpose=body.purpose,
                backend=body.backend,
                value=body.value.get_secret_value(),
                idempotency_key=idempotency_key,
            ),
        )
        return _secret_mutation_view(result)

    async def rotate_secret(
        binding_id: UUID,
        body: RotatePlatformSecretBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretMutationView:
        require_platform_configuration_step_up(actor)
        metadata = await reader.get_secret_binding(actor, binding_id)
        if metadata.purpose == "security.appointment_option_signing":
            raise PlatformConfigurationInvalid()
        if secret_service is None:
            raise PlatformSecretUnavailable()
        result = await secret_service.rotate(
            actor,
            RotatePlatformSecret(
                binding_id=binding_id,
                expected_revision=body.expected_revision,
                expected_backend_version=body.expected_backend_version,
                value=body.value.get_secret_value(),
                idempotency_key=idempotency_key,
            ),
        )
        return _secret_mutation_view(result)

    async def create_appointment_signing_keyring(
        body: CreateAppointmentSigningKeyringBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretMutationView:
        require_platform_configuration_step_up(actor)
        if appointment_signing_secret_service is None:
            raise PlatformSecretUnavailable()
        result = await appointment_signing_secret_service.create(
            actor,
            CreatePlatformSecret(
                purpose="security.appointment_option_signing",
                backend="openbao",
                value=create_appointment_option_keyring(body.key_id),
                idempotency_key=idempotency_key,
            ),
        )
        return _secret_mutation_view(result)

    async def rotate_appointment_signing_keyring(
        binding_id: UUID,
        body: RotateAppointmentSigningKeyringBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretMutationView:
        require_platform_configuration_step_up(actor)
        if appointment_signing_secret_service is None:
            raise PlatformSecretUnavailable()
        result = await appointment_signing_secret_service.rotate_transformed(
            actor,
            RotatePlatformSecretIntent(
                binding_id=binding_id,
                expected_revision=body.expected_revision,
                expected_backend_version=body.expected_backend_version,
                idempotency_key=idempotency_key,
            ),
            expected_purpose="security.appointment_option_signing",
            transform=lambda current: rotate_appointment_option_keyring(
                current,
                new_key_id=body.new_key_id,
            ),
        )
        return _secret_mutation_view(result)

    async def revoke_secret(
        binding_id: UUID,
        body: RevokePlatformSecretBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> SecretMutationView:
        require_platform_configuration_step_up(actor)
        metadata = await reader.get_secret_binding(actor, binding_id)
        selected_secret_service = (
            appointment_signing_secret_service
            if metadata.purpose == "security.appointment_option_signing"
            else secret_service
        )
        if selected_secret_service is None:
            raise PlatformSecretUnavailable()
        result = await selected_secret_service.revoke(
            actor,
            RevokePlatformSecret(
                binding_id=binding_id,
                expected_revision=body.expected_revision,
                expected_backend_version=body.expected_backend_version,
                idempotency_key=idempotency_key,
            ),
        )
        return _secret_mutation_view(result)

    async def stage_configuration(
        configuration_kind: str,
        body: StageConfigurationBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationMutationView:
        require_platform_configuration_step_up(actor)
        try:
            if configuration_kind == "email.delivery" and body.provider_kind == "smtp":
                parse_smtp_configuration(body.configuration)
            elif configuration_kind == "communications.webhook" and body.provider_kind == "webhook":
                parse_webhook_configuration(body.configuration)
            elif (
                configuration_kind == "security.appointment_option_signing"
                and body.provider_kind == "hmac-sha256-keyring"
                and body.secret_binding_id is not None
                and not body.configuration
            ):
                pass
            else:
                raise PlatformConfigurationInvalid()
        except (TypeError, ValueError) as exc:
            raise PlatformConfigurationProviderInvalid() from exc
        result = await commands.stage(
            actor,
            StageConfiguration(
                configuration_kind=configuration_kind,
                provider_kind=body.provider_kind,
                configuration=body.configuration,
                secret_binding_id=body.secret_binding_id,
                idempotency_key=idempotency_key,
            ),
        )
        return _mutation_view(result)

    async def validate_configuration(
        configuration_kind: str,
        revision: int,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationMutationView:
        require_platform_configuration_step_up(actor)
        return _mutation_view(
            await provider_validation.validate(
                actor,
                configuration_kind=configuration_kind,
                revision=revision,
                idempotency_key=idempotency_key,
            )
        )

    async def test_provider(
        configuration_kind: str,
        revision: int,
        body: ProviderTestBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ProviderTestView:
        require_platform_configuration_step_up(actor)
        result = await provider_test.test(
            actor,
            configuration_kind=configuration_kind,
            revision=revision,
            destination=body.destination,
            idempotency_key=idempotency_key,
        )
        return _provider_test_view(result)

    async def activate_configuration(
        configuration_kind: str,
        revision: int,
        body: ActivateConfigurationBody,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationMutationView:
        require_platform_configuration_step_up(actor)
        return _mutation_view(
            await commands.activate(
                actor,
                ActivateConfiguration(
                    configuration_kind=configuration_kind,
                    revision=revision,
                    expected_active_revision=body.expected_active_revision,
                    idempotency_key=idempotency_key,
                ),
            )
        )

    async def disable_configuration(
        configuration_kind: str,
        revision: int,
        _bearer: _NativeBearer,
        idempotency_key: _IdempotencyKey,
        actor: Annotated[PlatformActorContext, Depends(authenticated_actor)],
    ) -> ConfigurationMutationView:
        require_platform_configuration_step_up(actor)
        return _mutation_view(
            await commands.disable(
                actor,
                DisableConfiguration(
                    configuration_kind=configuration_kind,
                    revision=revision,
                    idempotency_key=idempotency_key,
                ),
            )
        )

    read_responses = {status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 422)}
    mutation_responses = {
        status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 409, 422)
    }
    add_capability_route(
        router,
        "/v1/platform/configurations",
        list_configurations,
        capability="platform.configuration.read",
        methods=["GET"],
        operation_id="platform_configuration_list",
        owner="platform_configuration",
        response_model=ConfigurationRevisionListView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/configurations/{configuration_kind}",
        list_configuration_revisions,
        capability="platform.configuration.read",
        methods=["GET"],
        operation_id="platform_configuration_revision_list",
        owner="platform_configuration",
        response_model=ConfigurationRevisionListView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/configurations/{configuration_kind}/revisions/{revision}",
        get_configuration_revision,
        capability="platform.configuration.read",
        methods=["GET"],
        operation_id="platform_configuration_revision_get",
        owner="platform_configuration",
        response_model=ConfigurationRevisionView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/readiness",
        get_platform_readiness,
        capability="platform.readiness.read",
        methods=["GET"],
        operation_id="platform_readiness_get",
        owner="platform_configuration",
        response_model=PlatformReadinessView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/secrets/{binding_id}",
        get_secret_binding,
        capability="platform.configuration.read",
        methods=["GET"],
        operation_id="platform_secret_metadata_get",
        owner="platform_configuration",
        response_model=SecretBindingMetadataView,
        responses=read_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/secrets",
        create_secret,
        capability="platform.secret.write",
        methods=["POST"],
        operation_id="platform_secret_create",
        owner="platform_configuration",
        status_code=201,
        response_model=SecretMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/secrets/{binding_id}:rotate",
        rotate_secret,
        capability="platform.secret.rotate",
        methods=["POST"],
        operation_id="platform_secret_rotate",
        owner="platform_configuration",
        response_model=SecretMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/signing-keyrings/appointment-option",
        create_appointment_signing_keyring,
        capability="platform.secret.write",
        methods=["POST"],
        operation_id="platform_appointment_signing_keyring_create",
        owner="platform_configuration",
        status_code=201,
        response_model=SecretMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/signing-keyrings/appointment-option/{binding_id}:rotate",
        rotate_appointment_signing_keyring,
        capability="platform.secret.rotate",
        methods=["POST"],
        operation_id="platform_appointment_signing_keyring_rotate",
        owner="platform_configuration",
        response_model=SecretMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/secrets/{binding_id}:revoke",
        revoke_secret,
        capability="platform.secret.revoke",
        methods=["POST"],
        operation_id="platform_secret_revoke",
        owner="platform_configuration",
        response_model=SecretMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/configurations/{configuration_kind}/revisions",
        stage_configuration,
        capability="platform.configuration.stage",
        methods=["POST"],
        operation_id="platform_configuration_stage",
        owner="platform_configuration",
        status_code=201,
        response_model=ConfigurationMutationView,
        responses=mutation_responses,
    )
    add_capability_route(
        router,
        "/v1/platform/providers/{configuration_kind}/{revision}:test",
        test_provider,
        capability="platform.provider.test",
        methods=["POST"],
        operation_id="platform_provider_test",
        owner="platform_configuration",
        response_model=ProviderTestView,
        responses=mutation_responses,
    )
    for action, endpoint, capability in (
        ("validate", validate_configuration, "platform.configuration.validate"),
        ("activate", activate_configuration, "platform.configuration.activate"),
        ("disable", disable_configuration, "platform.configuration.disable"),
    ):
        add_capability_route(
            router,
            f"/v1/platform/configurations/{{configuration_kind}}/revisions/{{revision}}:{action}",
            endpoint,
            capability=capability,
            methods=["POST"],
            operation_id=f"platform_configuration_{action}",
            owner="platform_configuration",
            response_model=ConfigurationMutationView,
            responses=mutation_responses,
        )

    app.add_exception_handler(PlatformConfigurationError, platform_configuration_error_handler)
    app.include_router(router)


def require_platform_configuration_step_up(actor: PlatformActorContext) -> None:
    require_phishing_resistant_authentication(actor, now=datetime.now(UTC))


def _secret_mutation_view(result: SecretMutationResult) -> SecretMutationView:
    return SecretMutationView(
        binding_id=result.binding_id,
        revision=result.revision,
        backend_version=result.backend_version,
        status=result.status,
    )


def _provider_test_view(result: PlatformProviderTestResult) -> ProviderTestView:
    return ProviderTestView(
        fact_id=result.fact_id,
        outcome=result.outcome.value,
        detail_code=result.detail_code,
    )


def _mutation_view(result: ConfigurationMutationResult) -> ConfigurationMutationView:
    return ConfigurationMutationView(
        configuration_revision_id=result.configuration_revision_id,
        revision=result.revision,
        state=result.state,
    )


def _revision_view(row: ConfigurationRevision) -> ConfigurationRevisionView:
    return ConfigurationRevisionView(
        configuration_revision_id=row.configuration_revision_id,
        configuration_kind=row.configuration_kind,
        provider_kind=row.provider_kind,
        revision=row.revision,
        configuration=row.configuration,
        secret_binding_id=row.secret_binding_id,
        state=row.state,
        created_by_principal_id=row.created_by_principal_id,
        created_at=row.created_at,
        validated_at=row.validated_at,
        activated_at=row.activated_at,
        disabled_at=row.disabled_at,
    )


def _readiness_view(readiness: PlatformReadiness) -> PlatformReadinessView:
    return PlatformReadinessView(
        managed_smtp_source=readiness.managed_smtp_source,
        smtp_active_revision=readiness.smtp_active_revision,
        smtp_last_validated_at=readiness.smtp_last_validated_at,
        smtp_last_provider_test_outcome=readiness.smtp_last_provider_test_outcome,
        smtp_last_provider_test_at=readiness.smtp_last_provider_test_at,
        smtp_secret_configured=readiness.smtp_secret_configured,
        backup_evidence=readiness.backup_evidence,
        restore_drill=readiness.restore_drill,
        clone_fence=readiness.clone_fence,
        secret_store=readiness.secret_store,
        recovery_delivery_source=readiness.recovery_delivery_source,
        oidc=readiness.oidc,
    )


def _secret_view(row: SecretBindingMetadata) -> SecretBindingMetadataView:
    return SecretBindingMetadataView(
        binding_id=row.binding_id,
        purpose=row.purpose,
        backend=row.backend,
        backend_version=row.backend_version,
        revision=row.revision,
        last_rotated_at=row.rotated_at,
        status=row.status,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )
