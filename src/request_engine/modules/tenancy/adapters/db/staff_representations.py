"""Staff Representation delegation over the RE-owned definer backstop.

READ/PLAN: Python validates the closed scope vocabulary, provenance and key.
LOCK/VALIDATE: idempotency is acquired first, then the ordered staff roots and
current HUMAN ``staff.manage_authority`` manager are re-asserted before any
receipt replay. ``request_engine.replace_staff_representations`` locks target
membership/Principal (exact authority revision), authority Party and the actor's
delegable ceiling, then WRITE revokes/inserts only non-delegable rows. EMIT is one
append-only audit row in the same transaction.
"""

from typing import NoReturn, Protocol, cast, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.commands.staff_representations import (
    ReplaceStaffRepresentationsCommand,
    ReplaceStaffRepresentationsResult,
    StaffRepresentation,
    StaffRepresentationsState,
    validate_staff_representation_scopes,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

_AUTHORITY_CAPABILITY = "staff.manage_authority"


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or actor.recovery_restricted:
        raise StaffMembershipForbidden("staff authority administration requires a HUMAN actor")


def _provenance(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("provenance_reference must contain between 1 and 500 characters")
    return normalized


def _raise_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise StaffMembershipForbidden("staff Representation authority was denied") from exc
    if sqlstate == "P0002":
        raise StaffMembershipNotFound("staff membership or Party is not visible") from exc
    if sqlstate == "40001":
        raise StaffMembershipRevisionConflict("staff authority revision is stale") from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise StaffMembershipConflict("staff Representation state conflicts") from exc
    if sqlstate == "22023":
        raise StaffMembershipInputInvalid("staff Representation input was rejected") from exc
    raise exc


_ACTIVE_SCOPES = """
    SELECT scope_key FROM request_engine.representations
    WHERE organization_id = :org AND principal_id = :principal
      AND represented_party_id = :party AND status = 'active'
      AND valid_from <= clock_timestamp()
      AND (valid_until IS NULL OR valid_until > clock_timestamp())
    ORDER BY scope_key
"""


async def _active_scopes(
    session: AsyncSession, organization_id: UUID, principal_id: UUID, party_id: UUID
) -> tuple[str, ...]:
    rows = await session.execute(
        text(_ACTIVE_SCOPES),
        {"org": organization_id, "principal": principal_id, "party": party_id},
    )
    return tuple(sorted({str(value) for value in rows.scalars()}))


def _result_from_replay(replay: dict[str, object]) -> ReplaceStaffRepresentationsResult:
    def strings(key: str) -> tuple[str, ...]:
        value = replay.get(key)
        if not isinstance(value, list):
            raise RuntimeError(f"completed staff idempotency replay has invalid {key}")
        return tuple(str(item) for item in cast(list[object], value))

    revision = replay.get("authority_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        raise RuntimeError("completed staff idempotency replay has invalid authority_revision")
    return ReplaceStaffRepresentationsResult(
        membership_id=UUID(str(replay["membership_id"])),
        authority_party_id=UUID(str(replay["authority_party_id"])),
        authority_revision=revision,
        scopes=strings("scopes"),
        added=strings("added"),
        removed=strings("removed"),
    )


class PostgresStaffRepresentations:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_staff_representations(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffRepresentationsState:
        _require_human_actor(actor)
        if not actor.allows("staff.read"):
            raise StaffMembershipForbidden("staff inspection requires staff.read")
        async with actor_transaction(self._session_factory, actor) as session:
            permitted = (
                await session.execute(
                    text("""SELECT EXISTS (
                SELECT 1 FROM request_engine.principals p
                JOIN request_engine.staff_memberships m ON m.principal_id = p.id
                    AND m.organization_id = p.organization_id AND m.status = 'active'
                JOIN request_engine.principal_authority_grants g ON g.principal_id = p.id
                    AND g.organization_id = p.organization_id AND g.status = 'active'
                    AND g.authority_plane = 'tenant_control' AND g.capability_key = 'staff.read'
                WHERE p.id = :actor AND p.organization_id = :org AND p.active
                    AND p.principal_kind = 'human' AND p.principal_plane = 'tenant')"""),
                    {"actor": actor.principal_id, "org": actor.organization_id},
                )
            ).scalar_one()
            if not permitted:
                raise StaffMembershipForbidden("Current staff inspection authority was withdrawn")
            member = (
                (
                    await session.execute(
                        text("""SELECT m.principal_id, p.authority_revision
                    FROM request_engine.staff_memberships m
                    JOIN request_engine.principals p ON p.organization_id = m.organization_id
                        AND p.id = m.principal_id
                    WHERE m.organization_id = :org AND m.id = :membership"""),
                        {"org": actor.organization_id, "membership": membership_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if member is None:
                raise StaffMembershipNotFound("staff membership is not visible in this tenant")
            rows = (
                (
                    await session.execute(
                        text("""SELECT id, represented_party_id, scope_key, authority_kind,
                        delegable, granted_by_principal_id, valid_from, valid_until, revision
                    FROM request_engine.representations
                    WHERE organization_id = :org AND principal_id = :principal
                      AND status = 'active'
                      AND valid_from <= clock_timestamp()
                      AND (valid_until IS NULL OR valid_until > clock_timestamp())
                    ORDER BY represented_party_id, scope_key, id"""),
                        {"org": actor.organization_id, "principal": member["principal_id"]},
                    )
                )
                .mappings()
                .all()
            )
        return StaffRepresentationsState(
            membership_id=membership_id,
            principal_id=member["principal_id"],
            authority_revision=int(member["authority_revision"]),
            representations=tuple(
                StaffRepresentation(
                    representation_id=row["id"],
                    authority_party_id=row["represented_party_id"],
                    scope_key=str(row["scope_key"]),
                    authority_kind=str(row["authority_kind"]),
                    delegable=bool(row["delegable"]),
                    granted_by_principal_id=row["granted_by_principal_id"],
                    valid_from=row["valid_from"],
                    valid_until=row["valid_until"],
                    revision=int(row["revision"]),
                )
                for row in rows
            ),
        )

    async def replace_staff_representations(
        self, actor: ActorContext, command: ReplaceStaffRepresentationsCommand
    ) -> ReplaceStaffRepresentationsResult:
        _require_human_actor(actor)
        if not actor.allows(_AUTHORITY_CAPABILITY):
            raise StaffMembershipForbidden("staff command capability is absent from actor context")
        if command.expected_authority_revision <= 0:
            raise ValueError("expected_authority_revision must be positive")
        desired = validate_staff_representation_scopes(command.desired_scopes)
        provenance = _provenance(command.provenance_reference)
        idempotency_key = command.idempotency_key.strip()
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        fingerprint = command_fingerprint(
            _AUTHORITY_CAPABILITY,
            {
                "operation": "staff_representations_replace",
                "membership_id": command.membership_id,
                "authority_party_id": command.authority_party_id,
                "expected_authority_revision": command.expected_authority_revision,
                "desired_scopes": desired,
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
            try:
                # Completed receipts never grant authority to a stale context.
                await session.execute(
                    text("SELECT request_cmd.lock_staff_command_authority(:capability)"),
                    {"capability": _AUTHORITY_CAPABILITY},
                )
            except DBAPIError as exc:
                _raise_db_error(exc)
            if replay is not None:
                return _result_from_replay(replay)
            target = (
                await session.execute(
                    text(
                        "SELECT principal_id FROM request_engine.staff_memberships "
                        "WHERE organization_id = :org AND id = :membership"
                    ),
                    {"org": actor.organization_id, "membership": command.membership_id},
                )
            ).scalar_one_or_none()
            before = (
                await _active_scopes(
                    session, actor.organization_id, target, command.authority_party_id
                )
                if target is not None
                else ()
            )
            try:
                revision = int(
                    (
                        await session.execute(
                            text("""SELECT request_engine.replace_staff_representations(
                            :membership, :party, :expected, :desired, :provenance)"""),
                            {
                                "membership": command.membership_id,
                                "party": command.authority_party_id,
                                "expected": command.expected_authority_revision,
                                "desired": list(desired),
                                "provenance": provenance,
                            },
                        )
                    ).scalar_one()
                )
            except DBAPIError as exc:
                _raise_db_error(exc)
            assert target is not None  # the definer raised P0002 otherwise
            after = await _active_scopes(
                session, actor.organization_id, target, command.authority_party_id
            )
            result = ReplaceStaffRepresentationsResult(
                membership_id=command.membership_id,
                authority_party_id=command.authority_party_id,
                authority_revision=revision,
                scopes=after,
                added=tuple(sorted(set(after) - set(before))),
                removed=tuple(sorted(set(before) - set(after))),
            )
            await append_audit(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                command_name=_AUTHORITY_CAPABILITY,
                aggregate_kind="StaffMembership",
                aggregate_id=command.membership_id,
                idempotency_id=idempotency_id,
                details={
                    "action": "representation_replace",
                    "reason_code": "staff_representations_replaced",
                    "subject_kind": "StaffMembership",
                    "revision_before": command.expected_authority_revision,
                    "revision_after": revision,
                    "authority_party_id": str(command.authority_party_id),
                    "scopes_added": list(result.added),
                    "scopes_removed": list(result.removed),
                    "provenance_reference": provenance,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "membership_id": str(result.membership_id),
                    "authority_party_id": str(result.authority_party_id),
                    "authority_revision": result.authority_revision,
                    "scopes": list(result.scopes),
                    "added": list(result.added),
                    "removed": list(result.removed),
                },
            )
            return result
