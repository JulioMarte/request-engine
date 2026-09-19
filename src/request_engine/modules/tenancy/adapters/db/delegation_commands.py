from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.delegation import (
    CreateDelegationCommand,
    CreateDelegationResult,
    RevokeDelegationCommand,
)
from request_engine.modules.tenancy.application.errors import (
    DelegationConflict,
    DelegationForbidden,
    DelegationInputInvalid,
    DelegationNotFound,
    DelegationRevisionConflict,
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

_CREATE_CAPABILITY = "delegation.create"
_REVOKE_CAPABILITY = "delegation.revoke"


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


def _validate_delegatable_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("allowed_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane is not AuthorityPlane.OPERATIONAL:
            raise ValueError(f"capability is not operational authority: {capability}")
    return capabilities


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise DelegationForbidden("delegation creation requires a HUMAN actor")


def _raise_delegation_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise DelegationForbidden("delegation authority was denied") from exc
    if sqlstate == "P0002":
        raise DelegationNotFound("delegation is not visible in this tenant") from exc
    if sqlstate == "40001":
        raise DelegationRevisionConflict("delegation revision is stale") from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise DelegationConflict("delegation state conflicts with this request") from exc
    if sqlstate == "22023":
        raise DelegationInputInvalid("delegation input was rejected") from exc
    raise exc


def _replay_uuid(replay: dict[str, object], key: str) -> UUID:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed delegation idempotency replay has invalid {key}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError(f"completed delegation idempotency replay has invalid {key}") from exc


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed delegation idempotency replay has invalid {key}")
    return value


class PostgresDelegationCommands:
    """Typed, idempotent application boundary over RE-owned delegation functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_delegation(
        self,
        actor: ActorContext,
        command: CreateDelegationCommand,
    ) -> CreateDelegationResult:
        _require_human_actor(actor)
        if not command.purpose.strip():
            raise ValueError("purpose is required")
        allowed = _validate_delegatable_capabilities(command.allowed_capabilities)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        delegation_id = uuid4()
        fingerprint = command_fingerprint(
            _CREATE_CAPABILITY,
            {
                "delegate_principal_id": command.delegate_principal_id,
                "purpose": command.purpose,
                "allowed_capabilities": allowed,
                "not_before": command.not_before,
                "expires_at": command.expires_at,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_CREATE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return CreateDelegationResult(
                    delegation_id=_replay_uuid(replay, "delegation_id"),
                    revision=_replay_revision(replay, "revision"),
                )
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.create_delegation(
                            :delegation_id,
                            :delegator_principal_id,
                            :delegate_principal_id,
                            :purpose,
                            :allowed_capabilities,
                            :not_before,
                            :expires_at,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "delegation_id": delegation_id,
                        "delegator_principal_id": actor.principal_id,
                        "delegate_principal_id": command.delegate_principal_id,
                        "purpose": command.purpose,
                        "allowed_capabilities": list(allowed),
                        "not_before": command.not_before,
                        "expires_at": command.expires_at,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_delegation_db_error(exc)
            revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"delegation_id": str(delegation_id), "revision": revision},
            )
            return CreateDelegationResult(delegation_id=delegation_id, revision=revision)

    async def revoke_delegation(
        self,
        actor: ActorContext,
        command: RevokeDelegationCommand,
    ) -> int:
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _REVOKE_CAPABILITY,
            {
                "delegation_id": command.delegation_id,
                "expected_revision": command.expected_revision,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_REVOKE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.revoke_delegation(
                            :delegation_id,
                            :expected_revision,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "delegation_id": command.delegation_id,
                        "expected_revision": command.expected_revision,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_delegation_db_error(exc)
            revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"revision": revision},
            )
            return revision
