from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffCommand,
    InviteNativeStaffResult,
    ReplaceStaffAuthorityCommand,
    TransitionStaffMembershipCommand,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
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

_INVITE_CAPABILITY = "staff.invite"
_AUTHORITY_CAPABILITY = "staff.manage_authority"
_MEMBERSHIP_CAPABILITY = "staff.manage_membership"


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


def _validate_staff_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("desired_capabilities must not contain duplicates")
    for capability in capabilities:
        definition = capability_definition(capability)
        if definition is None or definition.key != capability:
            raise ValueError(f"unknown or non-canonical capability: {capability}")
        if definition.authority_plane not in {
            AuthorityPlane.TENANT_CONTROL,
            AuthorityPlane.OPERATIONAL,
        }:
            raise ValueError(f"capability is not tenant authority: {capability}")
    return capabilities


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise StaffMembershipForbidden("staff membership administration requires a HUMAN actor")


def _raise_staff_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise StaffMembershipForbidden("staff lifecycle authority was denied") from exc
    if sqlstate == "P0002":
        raise StaffMembershipNotFound("staff membership is not visible in this tenant") from exc
    if sqlstate == "40001":
        raise StaffMembershipRevisionConflict("staff lifecycle revision is stale") from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise StaffMembershipConflict("staff lifecycle state conflicts with this request") from exc
    if sqlstate == "22023":
        raise StaffMembershipInputInvalid("staff lifecycle input was rejected") from exc
    raise exc


def _replay_uuid(replay: dict[str, object], key: str) -> UUID:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed staff idempotency replay has invalid {key}")
    try:
        return UUID(value)
    except ValueError as exc:
        raise RuntimeError(f"completed staff idempotency replay has invalid {key}") from exc


def _replay_invitation(replay: dict[str, object]) -> InviteNativeStaffResult:
    return InviteNativeStaffResult(
        membership_id=_replay_uuid(replay, "membership_id"),
        principal_id=_replay_uuid(replay, "principal_id"),
        binding_id=_replay_uuid(replay, "binding_id"),
    )


def _replay_revision(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed staff idempotency replay has invalid {key}")
    return value


class PostgresStaffMembershipCommands:
    """Typed, idempotent application boundary over RE-owned Staff lifecycle functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def invite_native_staff(
        self,
        actor: ActorContext,
        command: InviteNativeStaffCommand,
    ) -> InviteNativeStaffResult:
        _require_human_actor(actor)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _INVITE_CAPABILITY,
            {
                "identity_authority_id": command.identity_authority_id,
                "native_identity_id": command.native_identity_id,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=_INVITE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_invitation(replay)

            invitation = InviteNativeStaffResult(
                membership_id=uuid4(),
                principal_id=uuid4(),
                binding_id=uuid4(),
            )
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.invite_native_staff(
                            :membership_id,
                            :principal_id,
                            :binding_id,
                            :identity_authority_id,
                            :native_identity_id,
                            CAST(NULL AS uuid),
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "membership_id": invitation.membership_id,
                        "principal_id": invitation.principal_id,
                        "binding_id": invitation.binding_id,
                        "identity_authority_id": command.identity_authority_id,
                        "native_identity_id": command.native_identity_id,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_staff_db_error(exc)
            returned_binding_id = result.scalar_one()
            if returned_binding_id != invitation.binding_id:
                raise RuntimeError("staff invitation returned an unexpected binding identifier")
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "membership_id": str(invitation.membership_id),
                    "principal_id": str(invitation.principal_id),
                    "binding_id": str(invitation.binding_id),
                },
            )
            return invitation

    async def replace_staff_authority(
        self,
        actor: ActorContext,
        command: ReplaceStaffAuthorityCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = _validate_staff_capabilities(command.desired_capabilities)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _AUTHORITY_CAPABILITY,
            {
                "membership_id": command.membership_id,
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
                        SELECT request_engine.replace_staff_authority(
                            :membership_id,
                            :expected_authority_revision,
                            :desired_capabilities,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "membership_id": command.membership_id,
                        "expected_authority_revision": command.expected_authority_revision,
                        "desired_capabilities": list(desired),
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_staff_db_error(exc)
            authority_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"authority_revision": authority_revision},
            )
            return authority_revision

    async def transition_staff_membership(
        self,
        actor: ActorContext,
        command: TransitionStaffMembershipCommand,
    ) -> int:
        _require_human_actor(actor)
        if command.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            _MEMBERSHIP_CAPABILITY,
            {
                "membership_id": command.membership_id,
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
                capability=_MEMBERSHIP_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _replay_revision(replay, "membership_revision")
            try:
                result = await session.execute(
                    text(
                        """
                        SELECT request_engine.transition_staff_membership(
                            :membership_id,
                            :expected_revision,
                            :target_status,
                            :provenance_reference
                        )
                        """
                    ),
                    {
                        "membership_id": command.membership_id,
                        "expected_revision": command.expected_revision,
                        "target_status": command.target_status.value,
                        "provenance_reference": provenance,
                    },
                )
            except DBAPIError as exc:
                _raise_staff_db_error(exc)
            membership_revision = int(result.scalar_one())
            await complete_idempotency(
                session,
                idempotency_id,
                {"membership_revision": membership_revision},
            )
            return membership_revision
