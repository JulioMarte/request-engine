import secrets
from hashlib import sha256
from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.agent_governance import (
    ProvisionAgentCommand,
    ProvisionAgentResult,
    ReplaceAgentAuthorityCommand,
    TransitionAgentProfileCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceConflict,
    AgentGovernanceForbidden,
    AgentGovernanceInputInvalid,
    AgentGovernanceNotFound,
    AgentGovernanceRevisionConflict,
)
from request_engine.modules.tenancy.domain.agent_governance import AgentProfileStatus
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.context import ActorContext, PrincipalKind

_PROVISION_CAPABILITY = "agent.provision"
_AUTHORITY_CAPABILITY = "agent.manage_authority"
_LIFECYCLE_CAPABILITY = "agent.suspend"

_LIFECYCLE_TARGETS = frozenset(
    {AgentProfileStatus.ACTIVE, AgentProfileStatus.SUSPENDED, AgentProfileStatus.REVOKED}
)


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


def _validate_agent_operational_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("desired_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane is not AuthorityPlane.OPERATIONAL:
            raise ValueError(f"capability is not operational authority: {capability}")
    return capabilities


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise AgentGovernanceForbidden("agent governance requires a HUMAN actor")


def _raise_agent_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise AgentGovernanceForbidden("agent governance authority was denied") from exc
    if sqlstate == "P0002":
        raise AgentGovernanceNotFound("agent profile is not visible in this tenant") from exc
    if sqlstate == "40001":
        raise AgentGovernanceRevisionConflict("agent governance revision is stale") from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise AgentGovernanceConflict("agent governance state conflicts with this request") from exc
    if sqlstate == "22023":
        raise AgentGovernanceInputInvalid("agent governance input was rejected") from exc
    raise exc


def _replay_uuid(replay: dict[str, object], key: str) -> UUID:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed agent idempotency replay has invalid {key}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError(f"completed agent idempotency replay has invalid {key}") from exc


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed agent idempotency replay has invalid {key}")
    return value


class PostgresAgentGovernanceCommands:
    """Typed, idempotent application boundary over RE-owned Agent governance functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def provision_agent(
        self,
        actor: ActorContext,
        command: ProvisionAgentCommand,
    ) -> ProvisionAgentResult:
        _require_human_actor(actor)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _PROVISION_CAPABILITY,
            {
                "identity_authority_id": command.identity_authority_id,
                "display_name": command.display_name,
                "purpose": command.purpose,
                "sponsor_principal_id": command.sponsor_principal_id,
                "operating_mode": command.operating_mode.value,
                "credential_expires_at": command.credential_expires_at,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_PROVISION_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return ProvisionAgentResult(
                    principal_id=_replay_uuid(replay, "principal_id"),
                    workload_identity_id=_replay_uuid(replay, "workload_identity_id"),
                    credential_id=_replay_uuid(replay, "credential_id"),
                    binding_id=_replay_uuid(replay, "binding_id"),
                    profile_revision=_replay_revision(replay, "profile_revision"),
                    authority_revision=(
                        _replay_revision(replay, "authority_revision")
                        if "authority_revision" in replay
                        else None
                    ),
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
                        SELECT request_engine.provision_agent(
                            :principal_id,
                            :binding_id,
                            :workload_identity_id,
                            :credential_id,
                            :identity_authority_id,
                            :token_digest,
                            :token_fingerprint,
                            :credential_expires_at,
                            :display_name,
                            :purpose,
                            :sponsor_principal_id,
                            :operating_mode,
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
                        "credential_expires_at": command.credential_expires_at,
                        "display_name": command.display_name,
                        "purpose": command.purpose,
                        "sponsor_principal_id": command.sponsor_principal_id,
                        "operating_mode": command.operating_mode.value,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_agent_db_error(exc)
            profile_revision = int(result.scalar_one())
            authority_revision = int(
                (
                    await session.execute(
                        text(
                            "SELECT authority_revision FROM request_engine.principals "
                            "WHERE organization_id=:organization_id AND id=:principal_id"
                        ),
                        {"organization_id": actor.organization_id, "principal_id": principal_id},
                    )
                ).scalar_one()
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "principal_id": str(principal_id),
                    "workload_identity_id": str(workload_identity_id),
                    "credential_id": str(credential_id),
                    "binding_id": str(binding_id),
                    "profile_revision": profile_revision,
                    "authority_revision": authority_revision,
                },
            )
            return ProvisionAgentResult(
                principal_id=principal_id,
                workload_identity_id=workload_identity_id,
                credential_id=credential_id,
                binding_id=binding_id,
                profile_revision=profile_revision,
                authority_revision=authority_revision,
                workload_token=f"{credential_id}.{secret}",
            )

    async def replace_agent_authority(
        self,
        actor: ActorContext,
        command: ReplaceAgentAuthorityCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = _validate_agent_operational_capabilities(command.desired_capabilities)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _AUTHORITY_CAPABILITY,
            {
                "agent_principal_id": command.agent_principal_id,
                "expected_authority_revision": command.expected_authority_revision,
                "desired_capabilities": desired,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
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
                        SELECT request_engine.replace_agent_authority(
                            :agent_principal_id,
                            :expected_authority_revision,
                            :desired_capabilities,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "agent_principal_id": command.agent_principal_id,
                        "expected_authority_revision": command.expected_authority_revision,
                        "desired_capabilities": list(desired),
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_agent_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority_revision": authority_revision},
            )
            return authority_revision

    async def transition_agent_profile(
        self,
        actor: ActorContext,
        command: TransitionAgentProfileCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.target_status not in _LIFECYCLE_TARGETS:
            raise ValueError("target_status must be active, suspended, or revoked")
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _LIFECYCLE_CAPABILITY,
            {
                "agent_principal_id": command.agent_principal_id,
                "expected_revision": command.expected_revision,
                "target_status": command.target_status.value,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_LIFECYCLE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "profile_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.transition_agent_profile(
                            :agent_principal_id,
                            :expected_revision,
                            :target_status,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "agent_principal_id": command.agent_principal_id,
                        "expected_revision": command.expected_revision,
                        "target_status": command.target_status.value,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_agent_db_error(exc)
            profile_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"profile_revision": profile_revision},
            )
            return profile_revision
