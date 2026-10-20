"""Staff invitation proposals: agents propose, current HUMAN inviters decide (ADR 0019).

Proposal creation grants, stages and sends nothing. Approval stages the invitation
proof outside every lock, then in ONE transaction takes the ordinary invitation
gate (topology share, tenant staff root, current HUMAN ``staff.invite``), locks the
proposal row, revalidates it and writes the invitation through the same
``PostgresStaffInvitationCommands.insert_staged_invitation`` path used by
``staff_invitation_create``.
"""

from typing import NoReturn
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.staff_invitation_commands import (
    PostgresStaffInvitationCommands,
)
from request_engine.modules.tenancy.application.commands.staff_invitation_proposals import (
    PROPOSAL_DISPLAY_NAME_MAX,
    PROPOSAL_NOTE_MAX,
    PROPOSAL_REJECTION_REASON_MAX,
    ApproveStaffInvitationProposalCommand,
    ProposeStaffInvitationCommand,
    RejectStaffInvitationProposalCommand,
    StaffInvitationProposal,
    StaffInvitationProposalStatus,
    optional_text,
)
from request_engine.modules.tenancy.application.commands.staff_invitations import (
    normalize_invitation_email,
)
from request_engine.modules.tenancy.application.errors import (
    StaffInvitationProposalDuplicate,
    StaffInvitationProposalNotPending,
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

PROPOSE_CAPABILITY = "staff.propose_invitation"
_DECIDE_CAPABILITY = "staff.invite"
_READ_CAPABILITY = "staff.read"
# Idempotency scopes are per decision kind so a key can never replay across commands.
_APPROVE_SCOPE = "staff.invitation_proposal.approve"
_REJECT_SCOPE = "staff.invitation_proposal.reject"
_PROPOSER_KINDS = frozenset({PrincipalKind.HUMAN, PrincipalKind.AGENT})
_PROJECTION = """
    SELECT p.id AS proposal_id,p.organization_id,p.email,p.display_name,p.note,p.status,
        p.revision,p.proposed_by_principal_id,pr.principal_kind AS proposed_by_principal_kind,
        ap.display_name AS proposed_by_display_name,p.created_at,p.decided_at,
        p.decided_by_principal_id,p.invitation_id,p.rejection_reason
    FROM request_engine.staff_invitation_proposals p
    JOIN request_engine.principals pr ON pr.id=p.proposed_by_principal_id
        AND pr.organization_id=p.organization_id
    LEFT JOIN request_engine.agent_profiles ap ON ap.principal_id=p.proposed_by_principal_id
        AND ap.organization_id=p.organization_id
"""
_DUPLICATE_CONSTRAINTS = frozenset(
    {"staff_invitation_proposals_pending_email_uq", "staff_invitation_pending_email"}
)


def _require_human(actor: ActorContext, capability: str) -> None:
    if (
        actor.principal_kind is not PrincipalKind.HUMAN
        or not actor.allows(capability)
        or actor.recovery_restricted
    ):
        raise StaffMembershipForbidden("Active HUMAN staff authority is required")


def _require_proposer(actor: ActorContext) -> None:
    if (
        actor.principal_kind not in _PROPOSER_KINDS
        or not actor.allows(PROPOSE_CAPABILITY)
        or actor.recovery_restricted
    ):
        raise StaffMembershipForbidden("Staff invitation proposal authority is required")


def _bounded(value: str, *, maximum: int, label: str) -> str:
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= maximum:
        raise StaffMembershipInputInvalid(f"{label} must contain 1 to {maximum} characters")
    return trimmed


def _optional(value: str | None, *, maximum: int, label: str) -> str | None:
    try:
        return optional_text(value, maximum=maximum)
    except ValueError as exc:
        raise StaffMembershipInputInvalid(f"{label} is too long") from exc


def _decision_input(expected_revision: int, provenance_reference: str, idempotency_key: str) -> str:
    if expected_revision < 1 or not idempotency_key.strip():
        raise StaffMembershipInputInvalid("Invalid revision or idempotency key")
    return _bounded(provenance_reference, maximum=500, label="Provenance")


def _db_error(exc: DBAPIError) -> NoReturn:
    code = getattr(exc.orig, "sqlstate", None)
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        # asyncpg keeps structured diagnostics on the driver cause; never parse text.
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
    if code == "23505" and constraint in _DUPLICATE_CONSTRAINTS:
        raise StaffInvitationProposalDuplicate("A pending proposal or invitation exists") from exc
    if code in {"42501", "28000"}:
        raise StaffMembershipForbidden("Staff invitation proposal authority denied") from exc
    if code == "P0002":
        raise StaffMembershipNotFound("Proposal unavailable") from exc
    if code == "40001":
        raise StaffMembershipRevisionConflict("Proposal revision changed") from exc
    if code in {"23505", "23514", "55000"}:
        raise StaffMembershipConflict("Proposal state conflicts") from exc
    raise exc


def _validate_pending(row: StaffInvitationProposal, expected_revision: int) -> None:
    if row.revision != expected_revision:
        raise StaffMembershipRevisionConflict("Proposal changed")
    if row.status != StaffInvitationProposalStatus.PENDING:
        raise StaffInvitationProposalNotPending("Proposal was already decided")


class PostgresStaffInvitationProposalCommands:
    def __init__(
        self, session_factory: SessionFactory, *, invitations: PostgresStaffInvitationCommands
    ) -> None:
        self._sessions = session_factory
        self._invitations = invitations

    async def propose(
        self, actor: ActorContext, command: ProposeStaffInvitationCommand
    ) -> StaffInvitationProposal:
        _require_proposer(actor)
        try:
            email = normalize_invitation_email(command.email)
        except ValueError as exc:
            raise StaffMembershipInputInvalid("Invalid email address") from exc
        provenance = _bounded(command.provenance_reference, maximum=500, label="Provenance")
        display_name = _optional(
            command.display_name, maximum=PROPOSAL_DISPLAY_NAME_MAX, label="Display name"
        )
        note = _optional(command.note, maximum=PROPOSAL_NOTE_MAX, label="Note")
        if not command.idempotency_key.strip():
            raise StaffMembershipInputInvalid("Idempotency key is required")
        proposal_id = uuid5(
            NAMESPACE_URL,
            "staff-invitation-proposal:"
            f"{actor.organization_id}:{actor.principal_id}:{command.idempotency_key}",
        )
        fingerprint = command_fingerprint(
            "staff.invitation_proposal.create",
            {"email": email, "name": display_name, "note": note, "provenance": provenance},
        )
        try:
            async with actor_transaction(self._sessions, actor) as session:
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    capability=PROPOSE_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return await self._view(session, UUID(str(replay["proposal_id"])))
                # Advisory early answer only; approval relies on the unique pending
                # invitation index under the staff root lock.
                pending_invitation = (
                    await session.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM request_engine.staff_invitations "
                            "WHERE email=:email AND status='pending' "
                            "AND expires_at > clock_timestamp())"
                        ),
                        {"email": email},
                    )
                ).scalar_one()
                if pending_invitation:
                    raise StaffInvitationProposalDuplicate("A pending invitation exists")
                await session.execute(
                    text("""INSERT INTO request_engine.staff_invitation_proposals
                    (id,organization_id,email,display_name,note,proposed_by_principal_id,
                     provenance_reference)
                    VALUES(:id,:org,:email,:name,:note,:actor,:provenance)"""),
                    {
                        "id": proposal_id,
                        "org": actor.organization_id,
                        "email": email,
                        "name": display_name,
                        "note": note,
                        "actor": actor.principal_id,
                        "provenance": provenance,
                    },
                )
                await self._audit(session, actor, proposal_id, idem, "create", 0, 1, provenance)
                await complete_idempotency(session, idem, {"proposal_id": str(proposal_id)})
                return await self._view(session, proposal_id)
        except DBAPIError as exc:
            _db_error(exc)

    async def list(
        self,
        actor: ActorContext,
        *,
        status: StaffInvitationProposalStatus | None,
        after: UUID | None,
        limit: int,
    ) -> tuple[StaffInvitationProposal, ...]:
        _require_human(actor, _READ_CAPABILITY)
        if not 1 <= limit <= 101:
            raise StaffMembershipInputInvalid("Invalid page size")
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await self._invitations.assert_read_authority(session, actor)
                rows = (
                    (
                        await session.execute(
                            text(
                                _PROJECTION + " WHERE (CAST(:status AS text) IS NULL "
                                "OR p.status = CAST(:status AS text))"
                                " AND (CAST(:after AS uuid) IS NULL OR p.id > CAST(:after AS uuid))"
                                " ORDER BY p.id LIMIT :limit"
                            ),
                            {
                                "status": status.value if status is not None else None,
                                "after": after,
                                "limit": limit,
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
                return tuple(StaffInvitationProposal(**dict(row)) for row in rows)
        except DBAPIError as exc:
            _db_error(exc)

    async def get(self, actor: ActorContext, proposal_id: UUID) -> StaffInvitationProposal:
        """HUMAN ``staff.read`` sees any tenant proposal; a proposer sees only its own."""

        administrative = (
            actor.principal_kind is PrincipalKind.HUMAN
            and actor.allows(_READ_CAPABILITY)
            and not actor.recovery_restricted
        )
        if not administrative:
            _require_proposer(actor)
        try:
            async with actor_transaction(self._sessions, actor) as session:
                if administrative:
                    await self._invitations.assert_read_authority(session, actor)
                    return await self._view(session, proposal_id)
                return await self._view(session, proposal_id, proposer=actor.principal_id)
        except DBAPIError as exc:
            _db_error(exc)

    async def approve(
        self, actor: ActorContext, command: ApproveStaffInvitationProposalCommand
    ) -> StaffInvitationProposal:
        _require_human(actor, _DECIDE_CAPABILITY)
        provenance = _decision_input(
            command.expected_revision, command.provenance_reference, command.idempotency_key
        )
        if not 1 <= command.expires_in_hours <= 168:
            raise StaffMembershipInputInvalid("Invalid invitation expiry")
        fingerprint = command_fingerprint(
            _APPROVE_SCOPE,
            {
                "id": command.proposal_id,
                "revision": command.expected_revision,
                "hours": command.expires_in_hours,
                "provenance": provenance,
            },
        )
        replay = await self._precheck(
            actor,
            scope=_APPROVE_SCOPE,
            key=command.idempotency_key,
            fingerprint=fingerprint,
            proposal_id=command.proposal_id,
            expected_revision=command.expected_revision,
        )
        if replay is not None:
            return replay
        # One proposal can yield at most one invitation identity; a retried
        # approval stages the same provider case and the store keeps one proof.
        invitation_id = uuid5(
            NAMESPACE_URL,
            f"staff-invitation-proposal-approval:{actor.organization_id}:{command.proposal_id}",
        )
        staged = await self._invitations.stage_invitation_secret(
            invitation_id, command.expires_in_hours
        )
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                idem, replayed = await acquire_idempotency(
                    session,
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    capability=_APPROVE_SCOPE,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replayed is not None:
                    return await self._view(session, command.proposal_id)
                current = await self._lock(session, command.proposal_id)
                _validate_pending(current, command.expected_revision)
                await self._invitations.insert_staged_invitation(
                    session,
                    actor,
                    invitation_id=invitation_id,
                    email=current.email,
                    provenance=provenance,
                    staged=staged,
                    idempotency_id=idem,
                )
                await session.execute(
                    text("""UPDATE request_engine.staff_invitation_proposals
                    SET status='approved',revision=revision+1,decided_at=clock_timestamp(),
                        decided_by_principal_id=:actor,decision_provenance_reference=:provenance,
                        invitation_id=:invitation,updated_at=clock_timestamp()
                    WHERE id=:id"""),
                    {
                        "actor": actor.principal_id,
                        "provenance": provenance,
                        "invitation": invitation_id,
                        "id": command.proposal_id,
                    },
                )
                await self._audit(
                    session,
                    actor,
                    command.proposal_id,
                    idem,
                    "approve",
                    current.revision,
                    current.revision + 1,
                    provenance,
                    invitation_id=invitation_id,
                )
                await complete_idempotency(
                    session,
                    idem,
                    {"proposal_id": str(command.proposal_id), "invitation_id": str(invitation_id)},
                )
                return await self._view(session, command.proposal_id)
        except DBAPIError as exc:
            _db_error(exc)

    async def reject(
        self, actor: ActorContext, command: RejectStaffInvitationProposalCommand
    ) -> StaffInvitationProposal:
        _require_human(actor, _DECIDE_CAPABILITY)
        provenance = _decision_input(
            command.expected_revision, command.provenance_reference, command.idempotency_key
        )
        reason = _optional(command.reason, maximum=PROPOSAL_REJECTION_REASON_MAX, label="Reason")
        fingerprint = command_fingerprint(
            _REJECT_SCOPE,
            {
                "id": command.proposal_id,
                "revision": command.expected_revision,
                "reason": reason,
                "provenance": provenance,
            },
        )
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                idem, replayed = await acquire_idempotency(
                    session,
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    capability=_REJECT_SCOPE,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replayed is not None:
                    return await self._view(session, command.proposal_id)
                current = await self._lock(session, command.proposal_id)
                _validate_pending(current, command.expected_revision)
                await session.execute(
                    text("""UPDATE request_engine.staff_invitation_proposals
                    SET status='rejected',revision=revision+1,decided_at=clock_timestamp(),
                        decided_by_principal_id=:actor,decision_provenance_reference=:provenance,
                        rejection_reason=:reason,updated_at=clock_timestamp()
                    WHERE id=:id"""),
                    {
                        "actor": actor.principal_id,
                        "provenance": provenance,
                        "reason": reason,
                        "id": command.proposal_id,
                    },
                )
                await self._audit(
                    session,
                    actor,
                    command.proposal_id,
                    idem,
                    "reject",
                    current.revision,
                    current.revision + 1,
                    provenance,
                )
                await complete_idempotency(session, idem, {"proposal_id": str(command.proposal_id)})
                return await self._view(session, command.proposal_id)
        except DBAPIError as exc:
            _db_error(exc)

    async def _precheck(
        self,
        actor: ActorContext,
        *,
        scope: str,
        key: str,
        fingerprint: str,
        proposal_id: UUID,
        expected_revision: int,
    ) -> StaffInvitationProposal | None:
        """Answer replays and stale/decided proposals before any external staging."""

        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                record = (
                    (
                        await session.execute(
                            text("""SELECT request_fingerprint,result_data,status
                            FROM request_engine.idempotency_records
                            WHERE principal_id=:actor AND capability=:scope
                            AND idempotency_key=:key"""),
                            {"actor": actor.principal_id, "scope": scope, "key": key},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if record is not None:
                    if record["request_fingerprint"] != fingerprint:
                        raise IdempotencyConflict(scope, key)
                    if record["status"] == "completed":
                        return await self._view(session, proposal_id)
                _validate_pending(await self._view(session, proposal_id), expected_revision)
                return None
        except DBAPIError as exc:
            _db_error(exc)

    async def _lock(self, session: AsyncSession, proposal_id: UUID) -> StaffInvitationProposal:
        locked = (
            await session.execute(
                text(
                    "SELECT id FROM request_engine.staff_invitation_proposals "
                    "WHERE id=:id FOR UPDATE"
                ),
                {"id": proposal_id},
            )
        ).scalar_one_or_none()
        if locked is None:
            raise StaffMembershipNotFound("Proposal unavailable")
        return await self._view(session, proposal_id)

    async def _view(
        self, session: AsyncSession, proposal_id: UUID, *, proposer: UUID | None = None
    ) -> StaffInvitationProposal:
        row = (
            (
                await session.execute(
                    text(
                        _PROJECTION + " WHERE p.id=:id AND (CAST(:proposer AS uuid) IS NULL "
                        "OR p.proposed_by_principal_id=CAST(:proposer AS uuid))"
                    ),
                    {"id": proposal_id, "proposer": proposer},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise StaffMembershipNotFound("Proposal unavailable")
        return StaffInvitationProposal(**dict(row))

    async def _audit(
        self,
        session: AsyncSession,
        actor: ActorContext,
        proposal_id: UUID,
        idempotency_id: UUID,
        action: str,
        before: int,
        after: int,
        provenance: str,
        *,
        invitation_id: UUID | None = None,
    ) -> None:
        details: dict[str, object] = {
            "action": action,
            "reason_code": f"staff_invitation_proposal_{action}",
            "revision_before": before,
            "revision_after": after,
            "provenance_reference": provenance,
        }
        if invitation_id is not None:
            details["invitation_id"] = str(invitation_id)
        await append_audit(
            session,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            command_name=f"staff.invitation_proposal.{action}",
            aggregate_kind="StaffInvitationProposal",
            aggregate_id=proposal_id,
            idempotency_id=idempotency_id,
            details=details,
        )
