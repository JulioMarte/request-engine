import secrets
from hashlib import sha256
from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.commands.integration_governance import (
    ProvisionIntegrationCommand,
    ProvisionIntegrationResult,
    ReplaceIntegrationAuthorityCommand,
    RotateIntegrationCredentialCommand,
    RotateIntegrationCredentialResult,
    TransitionIntegrationStatusCommand,
)
from request_engine.modules.tenancy.application.errors import (
    IntegrationGovernanceConflict,
    IntegrationGovernanceForbidden,
    IntegrationGovernanceInputInvalid,
    IntegrationGovernanceNotFound,
    IntegrationGovernanceRevisionConflict,
)
from request_engine.modules.tenancy.domain.integration_governance import (
    integration_credential_expiry,
    integration_transition_capability,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.context import ActorContext, PrincipalKind

_PROVISION_CAPABILITY = "integration.provision"
_AUTHORITY_CAPABILITY = "integration.manage_authority"


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _validate_provenance_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("provenance_reference must contain between 1 and 500 characters")
    return normalized


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


def _validate_integration_operational_capabilities(
    capabilities: tuple[str, ...],
) -> tuple[str, ...]:
    if len(capabilities) > 128:
        raise ValueError("desired_capabilities cannot exceed 128 entries")
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("desired_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane is not AuthorityPlane.OPERATIONAL:
            raise ValueError(f"capability is not operational authority: {capability}")
    return tuple(sorted(capabilities))


def require_integration_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise IntegrationGovernanceForbidden("integration governance requires a HUMAN actor")


def raise_integration_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise IntegrationGovernanceForbidden("integration governance authority was denied") from exc
    if sqlstate == "P0002":
        raise IntegrationGovernanceNotFound(
            "integration Principal is not visible in this tenant"
        ) from exc
    if sqlstate == "40001":
        raise IntegrationGovernanceRevisionConflict(
            "integration governance revision is stale"
        ) from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise IntegrationGovernanceConflict(
            "integration governance state conflicts with this request"
        ) from exc
    if sqlstate == "22023":
        raise IntegrationGovernanceInputInvalid(
            "integration governance input was rejected"
        ) from exc
    raise exc


def _replay_uuid(replay: dict[str, object], key: str) -> UUID:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed integration idempotency replay has invalid {key}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError(f"completed integration idempotency replay has invalid {key}") from exc


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed integration idempotency replay has invalid {key}")
    return value


async def _authorize_current_manager(session: AsyncSession, capability: str) -> None:
    # Revalidate even completed replays. The authenticated snapshot may be stale;
    # this boundary holds the actor/membership/grant locks until transaction end.
    try:
        await session.execute(
            text("SELECT request_cmd.assert_integration_manager(:capability)"),
            {"capability": capability},
        )
    except DBAPIError as exc:
        raise_integration_db_error(exc)


class PostgresIntegrationGovernanceCommands:
    """Typed, idempotent application boundary over RE-owned INTEGRATION functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def provision_integration(
        self,
        actor: ActorContext,
        command: ProvisionIntegrationCommand,
    ) -> ProvisionIntegrationResult:
        require_integration_human_actor(actor)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        expires_at = integration_credential_expiry(command.credential_expires_at)
        fingerprint = command_fingerprint(
            _PROVISION_CAPABILITY,
            {
                "identity_authority_id": command.identity_authority_id,
                "credential_expires_at": expires_at,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            await _authorize_current_manager(session, _PROVISION_CAPABILITY)
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_PROVISION_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return ProvisionIntegrationResult(
                    principal_id=_replay_uuid(replay, "principal_id"),
                    workload_identity_id=_replay_uuid(replay, "workload_identity_id"),
                    credential_id=_replay_uuid(replay, "credential_id"),
                    binding_id=_replay_uuid(replay, "binding_id"),
                    authority_revision=_replay_revision(replay, "authority_revision"),
                    workload_token=None,
                )

            principal_id = uuid4()
            binding_id = uuid4()
            workload_identity_id = uuid4()
            credential_id = uuid4()
            secret = secrets.token_urlsafe(32)
            token_digest = sha256(secret.encode("utf-8")).digest()
            token_fingerprint = token_digest.hex()[:16]
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.provision_integration(
                            :principal_id,
                            :binding_id,
                            :workload_identity_id,
                            :credential_id,
                            :identity_authority_id,
                            :token_digest,
                            :token_fingerprint,
                            :credential_expires_at,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "principal_id": principal_id,
                        "binding_id": binding_id,
                        "workload_identity_id": workload_identity_id,
                        "credential_id": credential_id,
                        "identity_authority_id": command.identity_authority_id,
                        "token_digest": token_digest,
                        "token_fingerprint": token_fingerprint,
                        "credential_expires_at": expires_at,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                raise_integration_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "principal_id": str(principal_id),
                    "workload_identity_id": str(workload_identity_id),
                    "credential_id": str(credential_id),
                    "binding_id": str(binding_id),
                    "authority_revision": authority_revision,
                },
            )
            return ProvisionIntegrationResult(
                principal_id=principal_id,
                workload_identity_id=workload_identity_id,
                credential_id=credential_id,
                binding_id=binding_id,
                authority_revision=authority_revision,
                workload_token=f"{credential_id}.{secret}",
            )

    async def replace_integration_authority(
        self,
        actor: ActorContext,
        command: ReplaceIntegrationAuthorityCommand,
    ) -> int:
        require_integration_human_actor(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = _validate_integration_operational_capabilities(command.desired_capabilities)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _AUTHORITY_CAPABILITY,
            {
                "integration_principal_id": command.integration_principal_id,
                "expected_authority_revision": command.expected_authority_revision,
                "desired_capabilities": desired,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            await _authorize_current_manager(session, _AUTHORITY_CAPABILITY)
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_AUTHORITY_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "authority_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.replace_integration_authority(
                            :integration_principal_id,
                            :expected_authority_revision,
                            :desired_capabilities,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "integration_principal_id": command.integration_principal_id,
                        "expected_authority_revision": command.expected_authority_revision,
                        "desired_capabilities": list(desired),
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                raise_integration_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority_revision": authority_revision},
            )
            return authority_revision

    async def transition_integration_status(
        self,
        actor: ActorContext,
        command: TransitionIntegrationStatusCommand,
    ) -> int:
        require_integration_human_actor(actor)
        capability = integration_transition_capability(command.target_status)
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            capability,
            {
                "integration_principal_id": command.integration_principal_id,
                "expected_revision": command.expected_revision,
                "target_status": command.target_status.value,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            await _authorize_current_manager(session, capability)
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=capability,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "authority_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.set_integration_status(
                            :integration_principal_id,
                            :expected_revision,
                            :target_status,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "integration_principal_id": command.integration_principal_id,
                        "expected_revision": command.expected_revision,
                        "target_status": command.target_status.value,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                raise_integration_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority_revision": authority_revision},
            )
            return authority_revision

    async def rotate_integration_credential(
        self,
        actor: ActorContext,
        command: RotateIntegrationCredentialCommand,
    ) -> RotateIntegrationCredentialResult:
        require_integration_human_actor(actor)
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        expires_at = integration_credential_expiry(command.credential_expires_at)
        fingerprint = command_fingerprint(
            "integration_credential_rotate",
            {
                "integration_principal_id": command.integration_principal_id,
                "expected_revision": command.expected_revision,
                "credential_expires_at": expires_at,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            await _authorize_current_manager(session, _PROVISION_CAPABILITY)
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_PROVISION_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return RotateIntegrationCredentialResult(
                    credential_id=_replay_uuid(replay, "credential_id"),
                    authority_revision=_replay_revision(replay, "authority_revision"),
                )
            credential_id = uuid4()
            secret = secrets.token_urlsafe(32)
            digest = sha256(secret.encode("utf-8")).digest()
            try:
                result = await session.execute(
                    text("""
                        SELECT request_cmd.rotate_integration_credential(
                            :principal_id, :expected_revision, :credential_id,
                            :digest, :fingerprint, :expires_at, :provenance
                        )
                    """),
                    {
                        "principal_id": command.integration_principal_id,
                        "expected_revision": command.expected_revision,
                        "credential_id": credential_id,
                        "digest": digest,
                        "fingerprint": digest.hex()[:16],
                        "expires_at": expires_at,
                        "provenance": provenance,
                    },
                )
            except DBAPIError as exc:
                raise_integration_db_error(exc)
            revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"credential_id": str(credential_id), "authority_revision": revision},
            )
            return RotateIntegrationCredentialResult(
                credential_id=credential_id,
                authority_revision=revision,
                workload_token=f"{credential_id}.{secret}",
            )
