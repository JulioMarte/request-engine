"""Revisioned invitation orchestration; provider staging never holds DB locks."""

import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.commands.staff_invitations import (
    ChangeStaffInvitationCommand,
    CreateStaffInvitationCommand,
    InvitationDeliveryIntent,
    StaffInvitation,
    normalize_invitation_email,
)
from request_engine.modules.tenancy.application.errors import (
    StaffInvitationIdentityAlreadyLinked,
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.staff_invitation import (
    StaffInvitationPreview,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.secrets.delivery import (
    RecoveryDeliveryUnavailable,
    RecoverySecretStaging,
    StagedRecoverySecret,
)
from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

_PROJECTION = """
    SELECT i.id AS invitation_id,i.organization_id,i.email,
        CASE WHEN i.status = 'pending' AND i.expires_at <= clock_timestamp()
            THEN 'expired' ELSE i.status END AS status,
        i.generation,i.revision,i.expires_at,i.created_at,i.membership_id,i.principal_id,i.binding_id,
        i.delivery_channel
    FROM request_engine.staff_invitations i
"""


@dataclass(frozen=True, slots=True)
class _ShareableProof:
    """Link-delivery proof held only in memory until returned once to the inviter."""

    secret: str
    digest: str
    expires_at: datetime


def _shareable_proof(invitation_id: UUID, expires_at: datetime) -> _ShareableProof:
    # Same proof shape and digest as the governed email path; never persisted raw.
    secret = f"{invitation_id}.{secrets.token_urlsafe(32)}"
    return _ShareableProof(
        secret=secret, digest=hashlib.sha256(secret.encode()).hexdigest(), expires_at=expires_at
    )


def _require_actor(actor: ActorContext, capability: str) -> None:
    if (
        actor.principal_kind is not PrincipalKind.HUMAN
        or not actor.allows(capability)
        or actor.recovery_restricted
    ):
        raise StaffMembershipForbidden("Active HUMAN staff authority is required")


def _provenance(value: str) -> str:
    if not 1 <= len(value.strip()) <= 500:
        raise StaffMembershipInputInvalid("Provenance must contain 1 to 500 characters")
    return value.strip()


def _db_error(exc: DBAPIError, *, acceptance: bool = False) -> None:
    code = getattr(exc.orig, "sqlstate", None)
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        # SQLAlchemy's asyncpg translation preserves structured diagnostics on
        # the original driver cause, not on its DBAPI wrapper. Never parse text.
        constraint = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
    if (
        acceptance
        and code == "23505"
        and constraint
        in {
            "principals_organization_id_principal_kind_external_subject_key",
            "identity_bindings_tenant_subject_live_uq",
        }
    ):
        raise StaffInvitationIdentityAlreadyLinked(
            "An existing tenant identity link needs review"
        ) from exc
    if code in {"42501", "28000"}:
        raise StaffMembershipForbidden("Invitation authority denied") from exc
    if code == "P0002":
        raise StaffMembershipNotFound("Invitation unavailable") from exc
    if code == "40001":
        raise StaffMembershipRevisionConflict("Invitation revision changed") from exc
    if code in {"23505", "23514", "55000"}:
        raise StaffMembershipConflict("Invitation state conflicts") from exc
    raise exc


class PostgresStaffInvitationCommands:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        secret_delivery: RecoverySecretStaging | None,
        delivery_recorder: InvitationDeliveryIntent | None,
        acceptance_url: str | None = None,
    ) -> None:
        self._sessions = session_factory
        self._secrets = secret_delivery
        self._recorder = delivery_recorder
        # Deployment-validated console URL (bootstrap); never caller supplied.
        self._acceptance_url = acceptance_url

    def _issued(self, invitation: StaffInvitation, proof: _ShareableProof) -> StaffInvitation:
        url = (
            None
            if self._acceptance_url is None
            else f"{self._acceptance_url.rstrip('/')}/{invitation.invitation_id}/accept"
            f"#token={quote(proof.secret, safe='')}"
        )
        return replace(invitation, acceptance_token=proof.secret, acceptance_url=url)

    async def _cancel_deliveries(
        self, session: AsyncSession, organization_id: UUID, invitation_id: UUID, channel: str
    ) -> None:
        """Fence queued email generations; a link-only invitation has none to fence.

        An email generation is only ever recorded through the recorder, and a later
        switch to ``link`` cancels it in that same transaction, so a ``link``
        current channel without a recorder cannot leave a deliverable email behind.
        """

        if self._recorder is None:
            if channel != "link":
                raise RecoveryDeliveryUnavailable("Invitation delivery recorder unavailable")
            return
        await self._recorder.cancel(
            session, organization_id=organization_id, invitation_id=invitation_id
        )

    async def list(
        self,
        actor: ActorContext,
        *,
        after: UUID | None = None,
        limit: int = 51,
    ) -> tuple[StaffInvitation, ...]:
        _require_actor(actor, "staff.read")
        if not 1 <= limit <= 101:
            raise StaffMembershipInputInvalid("Invalid page size")
        async with actor_transaction(self._sessions, actor) as session:
            await self.assert_read_authority(session, actor)
            rows = (
                (
                    await session.execute(
                        text(
                            _PROJECTION
                            + " WHERE (CAST(:after AS uuid) IS NULL OR i.id > CAST(:after AS uuid))"
                            " ORDER BY i.id LIMIT :limit"
                        ),
                        {"after": after, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )
            generations = tuple(
                (UUID(str(row["invitation_id"])), int(str(row["generation"]))) for row in rows
            )
            statuses: Mapping[tuple[UUID, int], str] = (
                await self._recorder.statuses(
                    session, organization_id=actor.organization_id, generations=generations
                )
                if self._recorder is not None and generations
                else {}
            )
            invitations: list[StaffInvitation] = []
            for row in rows:
                data = dict(row)
                key = (UUID(str(data["invitation_id"])), int(str(data["generation"])))
                data["delivery_status"] = statuses.get(key)
                invitations.append(StaffInvitation(**data))
            return tuple(invitations)

    async def get(self, actor: ActorContext, invitation_id: UUID) -> StaffInvitation:
        _require_actor(actor, "staff.read")
        async with actor_transaction(self._sessions, actor) as session:
            await self.assert_read_authority(session, actor)
            return await self.view(session, invitation_id)

    async def assert_read_authority(self, session: AsyncSession, actor: ActorContext) -> None:
        permitted = (
            await session.execute(
                text("""SELECT EXISTS (
            SELECT 1 FROM request_engine.principals p
            JOIN request_engine.staff_memberships m ON m.principal_id=p.id
                AND m.organization_id=p.organization_id AND m.status='active'
            JOIN request_engine.principal_authority_grants g ON g.principal_id=p.id
                AND g.organization_id=p.organization_id AND g.status='active'
                AND g.authority_plane='tenant_control' AND g.capability_key='staff.read'
            WHERE p.id=:actor AND p.organization_id=:org AND p.active
                AND p.principal_kind='human' AND p.principal_plane='tenant'
        )"""),
                {"actor": actor.principal_id, "org": actor.organization_id},
            )
        ).scalar_one()
        if not permitted:
            raise StaffMembershipForbidden("Current staff inspection authority was withdrawn")

    async def view(self, session: AsyncSession, invitation_id: UUID) -> StaffInvitation:
        row = (
            (await session.execute(text(_PROJECTION + " WHERE i.id = :id"), {"id": invitation_id}))
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise StaffMembershipNotFound("Invitation unavailable")
        data = dict(row)
        data["delivery_status"] = await self._delivery_status(session, data)
        return StaffInvitation(**data)

    async def _delivery_status(self, session: AsyncSession, data: dict[str, object]) -> str | None:
        if self._recorder is None:
            return None
        return await self._recorder.status(
            session,
            organization_id=UUID(str(data["organization_id"])),
            invitation_id=UUID(str(data["invitation_id"])),
            generation=int(str(data["generation"])),
        )

    async def _stage(
        self, invitation_id: UUID, generation: int, expires_at: datetime
    ) -> StagedRecoverySecret:
        if self._secrets is None or self._recorder is None:
            raise RecoveryDeliveryUnavailable("Staff invitation delivery is not configured")
        # Store may retain a concurrent candidate. Persist its digest, never ours.
        return await self._secrets.stage(
            case_id=invitation_id,
            generation=generation,
            secret=f"{invitation_id}.{secrets.token_urlsafe(32)}",
            expires_at=expires_at,
        )

    async def _completed_replay(
        self, actor: ActorContext, key: str, fingerprint: str
    ) -> StaffInvitation | None:
        if not key.strip():
            raise StaffMembershipInputInvalid("Idempotency key is required")
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                row = (
                    (
                        await session.execute(
                            text("""SELECT request_fingerprint,result_data,status
                FROM request_engine.idempotency_records
                WHERE principal_id=:actor AND capability='staff.invite'
                AND idempotency_key=:key"""),
                            {"actor": actor.principal_id, "key": key},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                if row["request_fingerprint"] != fingerprint:
                    raise IdempotencyConflict("staff.invite", key)
                if row["status"] == "completed":
                    return await self.view(session, UUID(str(row["result_data"]["invitation_id"])))
                return None
        except DBAPIError as exc:
            _db_error(exc)
            raise

    async def create(
        self, actor: ActorContext, command: CreateStaffInvitationCommand
    ) -> StaffInvitation:
        _require_actor(actor, "staff.invite")
        try:
            email = normalize_invitation_email(command.email)
        except ValueError as exc:
            raise StaffMembershipInputInvalid("Invalid email address") from exc
        provenance = _provenance(command.provenance_reference)
        if not 1 <= command.expires_in_hours <= 168 or not command.idempotency_key.strip():
            raise StaffMembershipInputInvalid("Invalid expiry or idempotency key")
        invitation_id = uuid5(
            NAMESPACE_URL,
            f"staff-invitation:{actor.organization_id}:{actor.principal_id}:{command.idempotency_key}",
        )
        intent: dict[str, object] = {
            "email": email,
            "hours": command.expires_in_hours,
            "provenance": provenance,
        }
        if command.delivery == "link":
            intent["delivery"] = "link"
        fingerprint = command_fingerprint("staff.invitation.create", intent)
        replay = await self._completed_replay(actor, command.idempotency_key, fingerprint)
        if replay is not None:
            return replay
        staged: StagedRecoverySecret | None = None
        proof: _ShareableProof | None = None
        if command.delivery == "link":
            proof = _shareable_proof(
                invitation_id, datetime.now(UTC) + timedelta(hours=command.expires_in_hours)
            )
        else:
            staged = await self.stage_invitation_secret(invitation_id, command.expires_in_hours)
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    capability="staff.invite",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return await self.view(session, UUID(str(replay["invitation_id"])))
                await self.insert_staged_invitation(
                    session,
                    actor,
                    invitation_id=invitation_id,
                    email=email,
                    provenance=provenance,
                    staged=staged,
                    idempotency_id=idem,
                    shareable=proof,
                )
                await complete_idempotency(session, idem, {"invitation_id": str(invitation_id)})
                created = await self.view(session, invitation_id)
                return created if proof is None else self._issued(created, proof)
        except DBAPIError as exc:
            _db_error(exc)
            raise

    async def stage_invitation_secret(
        self, invitation_id: UUID, expires_in_hours: int
    ) -> StagedRecoverySecret:
        """Stage generation-1 proof outside every authoritative DB transaction."""

        return await self._stage(
            invitation_id, 1, datetime.now(UTC) + timedelta(hours=expires_in_hours)
        )

    async def insert_staged_invitation(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        invitation_id: UUID,
        email: str,
        provenance: str,
        staged: StagedRecoverySecret | None,
        idempotency_id: UUID,
        shareable: _ShareableProof | None = None,
    ) -> None:
        """The single pending-invitation write path, inside the caller's transaction.

        Callers must already hold ``request_cmd.lock_staff_invitation_admin(NULL)``
        (topology gate, tenant staff root and current HUMAN ``staff.invite``). The
        row guard independently re-asserts the inviter, and Communications records
        the closed-purpose delivery intent in this same transaction.
        """

        await session.execute(
            text(
                "UPDATE request_engine.staff_invitations SET status='expired',"
                "revision=revision+1,updated_at=clock_timestamp() "
                "WHERE email=:email AND status='pending' "
                "AND expires_at <= clock_timestamp()"
            ),
            {"email": email},
        )
        proof = staged if shareable is None else shareable
        if proof is None:
            raise RecoveryDeliveryUnavailable("Staff invitation delivery is not configured")
        channel = "email" if shareable is None else "link"
        await session.execute(
            text("""INSERT INTO request_engine.staff_invitations
            (id,organization_id,email,invited_by_principal_id,provenance_reference,token_digest,
             expires_at,delivery_channel)
            VALUES(:id,:org,:email,:actor,:provenance,:digest,:expiry,:channel)"""),
            {
                "id": invitation_id,
                "org": actor.organization_id,
                "email": email,
                "actor": actor.principal_id,
                "provenance": provenance,
                "digest": proof.digest,
                "expiry": proof.expires_at,
                "channel": channel,
            },
        )
        if staged is not None:
            if self._recorder is None:
                raise RecoveryDeliveryUnavailable("Invitation delivery recorder unavailable")
            await self._recorder.record(
                session,
                organization_id=actor.organization_id,
                invitation_id=invitation_id,
                generation=1,
                destination_address=email,
                secret_reference=staged.reference,
                secret_digest=staged.digest,
                expires_at=staged.expires_at,
            )
        await self._audit(
            session, actor, invitation_id, idempotency_id, "create", 0, 1, provenance, channel
        )

    async def resend(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation:
        _require_actor(actor, "staff.invite")
        fingerprint = command_fingerprint("staff.invitation.resend", _change_intent(command))
        replay = await self._completed_replay(actor, command.idempotency_key, fingerprint)
        if replay is not None:
            return replay
        try:
            async with actor_transaction(self._sessions, actor) as session:
                await session.execute(text("SELECT request_cmd.lock_staff_invitation_admin(NULL)"))
                current = await self.view(session, command.invitation_id)
        except DBAPIError as exc:
            _db_error(exc)
            raise
        if current.revision != command.expected_revision:
            raise StaffMembershipRevisionConflict("Invitation changed")
        if current.status != "pending":
            raise StaffMembershipConflict("Only unexpired pending invitations can be resent")
        expires_at = datetime.now(UTC) + timedelta(hours=72)
        if command.delivery == "link":
            proof = _shareable_proof(command.invitation_id, expires_at)
            return self._issued(await self._change(actor, command, None, proof), proof)
        staged = await self._stage(command.invitation_id, current.generation + 1, expires_at)
        return await self._change(actor, command, staged)

    async def revoke(
        self, actor: ActorContext, command: ChangeStaffInvitationCommand
    ) -> StaffInvitation:
        _require_actor(actor, "staff.invite")
        return await self._change(actor, replace(command, delivery="email"), None)

    async def _change(
        self,
        actor: ActorContext,
        command: ChangeStaffInvitationCommand,
        staged: StagedRecoverySecret | None,
        shareable: _ShareableProof | None = None,
    ) -> StaffInvitation:
        provenance = _provenance(command.provenance_reference)
        proof = staged if shareable is None else shareable
        action = "resend" if proof is not None else "revoke"
        channel = None if proof is None else ("email" if shareable is None else "link")
        fingerprint = command_fingerprint(f"staff.invitation.{action}", _change_intent(command))
        try:
            async with actor_transaction(self._sessions, actor) as session:
                row = (
                    (
                        await session.execute(
                            text("SELECT * FROM request_cmd.lock_staff_invitation_admin(:id)"),
                            {"id": command.invitation_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise StaffMembershipNotFound("Invitation unavailable")
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=actor.organization_id,
                    principal_id=actor.principal_id,
                    capability="staff.invite",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return await self.view(session, command.invitation_id)
                if row["revision"] != command.expected_revision:
                    raise StaffMembershipRevisionConflict("Invitation changed")
                if row["status"] != "pending" or row["expires_at"] <= datetime.now(UTC):
                    raise StaffMembershipConflict("Only unexpired pending invitations can change")
                await self._cancel_deliveries(
                    session,
                    actor.organization_id,
                    command.invitation_id,
                    str(row["delivery_channel"]),
                )
                if proof is None:
                    await session.execute(
                        text(
                            "UPDATE request_engine.staff_invitations SET status='revoked',"
                            "revision=revision+1,updated_at=clock_timestamp() WHERE id=:id"
                        ),
                        {"id": command.invitation_id},
                    )
                else:
                    await session.execute(
                        text(
                            "UPDATE request_engine.staff_invitations SET generation=generation+1,"
                            "token_digest=:digest,expires_at=:expiry,revision=revision+1,"
                            "delivery_channel=:channel,updated_at=clock_timestamp() WHERE id=:id"
                        ),
                        {
                            "id": command.invitation_id,
                            "digest": proof.digest,
                            "expiry": proof.expires_at,
                            "channel": channel,
                        },
                    )
                    if staged is not None:
                        if self._recorder is None:
                            raise RecoveryDeliveryUnavailable(
                                "Invitation delivery recorder unavailable"
                            )
                        await self._recorder.record(
                            session,
                            organization_id=actor.organization_id,
                            invitation_id=command.invitation_id,
                            generation=int(row["generation"]) + 1,
                            destination_address=str(row["email"]),
                            secret_reference=staged.reference,
                            secret_digest=staged.digest,
                            expires_at=staged.expires_at,
                        )
                await self._audit(
                    session,
                    actor,
                    command.invitation_id,
                    idem,
                    action,
                    command.expected_revision,
                    command.expected_revision + 1,
                    provenance,
                    channel,
                )
                await complete_idempotency(
                    session, idem, {"invitation_id": str(command.invitation_id)}
                )
                return await self.view(session, command.invitation_id)
        except DBAPIError as exc:
            _db_error(exc)
            raise

    async def accept(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitation:
        subject = authenticated.subject
        if (
            authenticated.authentication_method != "native_session"
            or subject.subject_class is not AuthenticatedSubjectClass.HUMAN
            or subject.metadata.get("recovery_restricted") == "true"
        ):
            raise StaffMembershipForbidden("Normal native HUMAN authentication required")
        if (
            not token.startswith(f"{invitation_id}.")
            or len(token) > 200
            or not authenticated.credential_id
        ):
            raise StaffMembershipNotFound("Invitation unavailable")
        identity = UUID(subject.subject_id)
        try:
            async with self._sessions() as session, session.begin():
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM request_cmd.lock_staff_invitation_acceptance("
                                ":id,:digest,:authority,:identity,:session)"
                            ),
                            {
                                "id": invitation_id,
                                "digest": hashlib.sha256(token.encode()).hexdigest(),
                                "authority": UUID(subject.authority_id),
                                "identity": identity,
                                "session": UUID(authenticated.credential_id),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                if row["status"] == "accepted":
                    return await self.view(session, invitation_id)
                membership, principal, binding = uuid4(), uuid4(), uuid4()
                await session.execute(
                    text(
                        "SELECT request_cmd.materialize_invited_staff("
                        ":id,:digest,:authority,:identity,:session,:membership,:principal,:binding)"
                    ),
                    {
                        "id": invitation_id,
                        "authority": UUID(subject.authority_id),
                        "identity": identity,
                        "membership": membership,
                        "principal": principal,
                        "binding": binding,
                        "digest": hashlib.sha256(token.encode()).hexdigest(),
                        "session": UUID(authenticated.credential_id),
                    },
                )
                await self._cancel_deliveries(
                    session, row["organization_id"], invitation_id, str(row["delivery_channel"])
                )
                return await self.view(session, invitation_id)
        except DBAPIError as exc:
            _db_error(exc, acceptance=True)
            raise

    async def preview(
        self, authenticated: AuthenticatedHttpSubject, invitation_id: UUID, token: str
    ) -> StaffInvitationPreview:
        subject = authenticated.subject
        if (
            authenticated.authentication_method != "native_session"
            or subject.subject_class is not AuthenticatedSubjectClass.HUMAN
            or subject.metadata.get("recovery_restricted") == "true"
        ):
            raise StaffMembershipForbidden("Normal native HUMAN authentication required")
        if (
            not token.startswith(f"{invitation_id}.")
            or not 40 <= len(token) <= 200
            or not authenticated.credential_id
        ):
            raise StaffMembershipNotFound("Invitation unavailable")
        try:
            async with self._sessions() as session, session.begin():
                # Reuse the existing proof/session consistency boundary. It derives
                # the tenant and holds its normal locks only for this short query;
                # it does not establish membership or emit a durable fact.
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM request_cmd.lock_staff_invitation_acceptance("
                                ":id,:digest,:authority,:identity,:session)"
                            ),
                            {
                                "id": invitation_id,
                                "digest": hashlib.sha256(token.encode()).hexdigest(),
                                "authority": UUID(subject.authority_id),
                                "identity": UUID(subject.subject_id),
                                "session": UUID(authenticated.credential_id),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                # The application role's existing SELECT remains tenant-RLS-bound.
                name = (
                    await session.execute(
                        text("SELECT display_name FROM request_engine.organizations WHERE id=:org"),
                        {"org": row["organization_id"]},
                    )
                ).scalar_one()
                return StaffInvitationPreview(
                    invitation_id=row["id"],
                    organization_id=row["organization_id"],
                    organization_display_name=str(name),
                    status=str(row["status"]),
                    expires_at=row["expires_at"],
                )
        except DBAPIError as exc:
            _db_error(exc)
            raise

    async def _audit(
        self,
        session: AsyncSession,
        actor: ActorContext,
        invitation_id: UUID,
        idem: UUID,
        action: str,
        before: int,
        after: int,
        provenance: str,
        channel: str | None = None,
    ) -> None:
        details: dict[str, object] = {
            "action": action,
            "reason_code": f"staff_invitation_{action}",
            "revision_before": before,
            "revision_after": after,
            "provenance_reference": provenance,
        }
        if channel is not None:
            # Records that a shareable link was issued; never the proof itself.
            details["delivery_channel"] = channel
            details["shareable_link_issued"] = channel == "link"
        await append_audit(
            session,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            command_name=f"staff.invitation.{action}",
            aggregate_kind="StaffInvitation",
            aggregate_id=invitation_id,
            idempotency_id=idem,
            details=details,
        )


def _change_intent(command: ChangeStaffInvitationCommand) -> dict[str, object]:
    intent: dict[str, object] = {
        "id": command.invitation_id,
        "revision": command.expected_revision,
        "provenance": _provenance(command.provenance_reference),
    }
    if command.delivery == "link":
        intent["delivery"] = "link"
    return intent
