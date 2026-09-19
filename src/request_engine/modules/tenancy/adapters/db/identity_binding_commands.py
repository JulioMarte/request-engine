from typing import NoReturn, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.identity_binding import (
    IDENTITY_BINDING_CAPABILITY,
    TransitionIdentityBindingCommand,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityBindingLifecycleConflict,
    IdentityBindingLifecycleForbidden,
    IdentityBindingLifecycleInputInvalid,
    IdentityBindingLifecycleNotFound,
    IdentityBindingLifecycleRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind


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


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise IdentityBindingLifecycleForbidden(
            "identity binding administration requires a HUMAN actor"
        )


def _raise_identity_binding_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise IdentityBindingLifecycleForbidden("identity binding authority was denied") from exc
    if sqlstate == "P0002":
        raise IdentityBindingLifecycleNotFound(
            "identity binding is not visible in this tenant"
        ) from exc
    if sqlstate in {"40001", "40P01"}:
        raise IdentityBindingLifecycleRevisionConflict(
            "identity binding revision is stale"
        ) from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise IdentityBindingLifecycleConflict(
            "identity binding state conflicts with this request"
        ) from exc
    if sqlstate == "22023":
        raise IdentityBindingLifecycleInputInvalid("identity binding input was rejected") from exc
    raise exc


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed identity binding idempotency replay has invalid {key}")
    return value


class PostgresIdentityBindingCommands:
    """Typed, idempotent application boundary over RE-owned binding lifecycle."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def transition_identity_binding(
        self,
        actor: ActorContext,
        command: TransitionIdentityBindingCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            IDENTITY_BINDING_CAPABILITY,
            {
                "binding_id": command.binding_id,
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
                capability=IDENTITY_BINDING_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "binding_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.transition_identity_binding(
                            :binding_id,
                            :expected_revision,
                            :target_status,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "binding_id": command.binding_id,
                        "expected_revision": command.expected_revision,
                        "target_status": command.target_status.value,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_identity_binding_db_error(exc)
            binding_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"binding_revision": binding_revision},
            )
            return binding_revision
