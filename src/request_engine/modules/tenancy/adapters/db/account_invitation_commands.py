"""Control-plane account invitations: digest-only tokens, post-commit email (ADR 0021)."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Never
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountInvitationConflict,
    AccountInvitationDeliveryUnavailable,
    AccountInvitationError,
    AccountInvitationForbidden,
    AccountInvitationInvalid,
    AccountInvitationIssued,
    AccountInvitationMailer,
    AccountInvitationNotFound,
    AccountInvitationRevisionConflict,
    AccountInvitationRevoked,
    AccountInvitationSummary,
    CreateAccountInvitationCommand,
    RevokeAccountInvitationCommand,
)
from request_engine.modules.tenancy.domain.account_entitlement import AccountInvitationDelivery
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.secrets.delivery import DeliveryOutcome, RecoveryDeliveryError
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_NAMESPACE = UUID("5b0e6a43-2f6c-4f43-9a52-7f3c0d7f9a21")
_ISSUE_CAPABILITY = "organization.provision"
_READ_CAPABILITY = "platform.organization.read"
_DATABASE_ERRORS: dict[str, type[AccountInvitationError]] = {
    "RE409": AccountInvitationConflict,
    "23505": AccountInvitationConflict,
    "55000": AccountInvitationConflict,
    "22023": AccountInvitationInvalid,
    "23514": AccountInvitationInvalid,
    "P0002": AccountInvitationNotFound,
    "40001": AccountInvitationRevisionConflict,
    "40P01": AccountInvitationRevisionConflict,
    "42501": AccountInvitationForbidden,
    "28000": AccountInvitationForbidden,
}


class PostgresPlatformAccountInvitationCommands:
    def __init__(
        self,
        write_session_factory: SessionFactory,
        read_session_factory: SessionFactory,
        *,
        mailer: AccountInvitationMailer | None,
    ) -> None:
        self._write = write_session_factory
        self._read = read_session_factory
        self._mailer = mailer

    async def create(
        self, actor: PlatformActorContext, command: CreateAccountInvitationCommand
    ) -> AccountInvitationIssued:
        _require(actor, _ISSUE_CAPABILITY)
        email = command.delivery is AccountInvitationDelivery.EMAIL
        if email and self._mailer is None:
            raise AccountInvitationDeliveryUnavailable("account invitation email is unavailable")
        raw_token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(raw_token.encode("utf-8")).digest()
        intent = {
            "delivery": command.delivery.value,
            "email": command.email,
            "max_organizations": command.max_organizations,
            "expires_in_hours": command.expires_in_hours,
            "provenance_reference": command.provenance_reference.strip(),
        }
        key_digest = _sha256(command.idempotency_key.strip())
        invitation_id = uuid5(_NAMESPACE, f"invitation:{actor.principal_id}:{key_digest}")
        try:
            async with platform_actor_transaction(self._write, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_platform.create_account_invitation("
                            "CAST(:id AS uuid), CAST(:digest AS bytea), CAST(:fp AS text), "
                            "CAST(:channel AS text), CAST(:email AS text), "
                            "CAST(:max AS integer), CAST(:expires AS timestamptz), "
                            "CAST(:provenance AS text), CAST(:key AS text), "
                            "CAST(:intent AS text))"
                        ),
                        {
                            "id": invitation_id,
                            "digest": token_digest,
                            "fp": hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:16],
                            "channel": command.delivery.value,
                            "email": command.email,
                            "max": command.max_organizations,
                            "expires": datetime.now(UTC)
                            + timedelta(hours=command.expires_in_hours),
                            "provenance": command.provenance_reference.strip(),
                            "key": key_digest,
                            "intent": _sha256(json.dumps(intent, sort_keys=True)),
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        created = bool(row[1])
        delivery_status = None if row[4] is None else str(row[4])
        if email and created:
            # Outside every authoritative lock: the invitation row is committed.
            delivery_status = await self._deliver(actor, invitation_id, raw_token, command)
        return AccountInvitationIssued(
            invitation_id=UUID(str(row[0])),
            created=created,
            status=str(row[2]),
            revision=int(row[3]),
            delivery_status=delivery_status,
            expires_at=row[5],
            raw_token=raw_token if created and not email else None,
        )

    async def _deliver(
        self,
        actor: PlatformActorContext,
        invitation_id: UUID,
        raw_token: str,
        command: CreateAccountInvitationCommand,
    ) -> str:
        assert self._mailer is not None and command.email is not None
        try:
            outcome = await self._mailer.send(
                secret=raw_token,
                destination_reference=command.email,
                idempotency_key=f"account-invitation:{invitation_id}",
            )
            status = {
                DeliveryOutcome.DELIVERED: "sent",
                DeliveryOutcome.FAILED: "failed",
            }.get(outcome, "unknown")
        except RecoveryDeliveryError:
            status = "failed"
        try:
            async with platform_actor_transaction(self._write, actor) as session:
                recorded = (
                    await session.execute(
                        text(
                            "SELECT request_platform.record_account_invitation_delivery("
                            "CAST(:id AS uuid), CAST(:status AS text))"
                        ),
                        {"id": invitation_id, "status": status},
                    )
                ).scalar_one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return str(recorded)

    async def revoke(
        self, actor: PlatformActorContext, command: RevokeAccountInvitationCommand
    ) -> AccountInvitationRevoked:
        _require(actor, _ISSUE_CAPABILITY)
        intent = {
            "invitation_id": str(command.invitation_id),
            "expected_revision": command.expected_revision,
            "reason_code": command.reason_code,
        }
        try:
            async with platform_actor_transaction(self._write, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_platform.revoke_account_invitation("
                            "CAST(:id AS uuid), CAST(:revision AS bigint), "
                            "CAST(:reason AS text), CAST(:key AS text), CAST(:intent AS text))"
                        ),
                        {
                            "id": command.invitation_id,
                            "revision": command.expected_revision,
                            "reason": command.reason_code,
                            "key": _sha256(command.idempotency_key.strip()),
                            "intent": _sha256(json.dumps(intent, sort_keys=True)),
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return AccountInvitationRevoked(
            invitation_id=UUID(str(row[0])), status=str(row[1]), revision=int(row[2])
        )

    async def list(
        self,
        actor: PlatformActorContext,
        *,
        invitation_id: UUID | None,
        after: UUID | None,
        limit: int,
    ) -> tuple[AccountInvitationSummary, ...]:
        _require(actor, _READ_CAPABILITY)
        try:
            async with platform_actor_transaction(self._read, actor) as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_platform.read_account_invitations("
                            "CAST(:id AS uuid), CAST(:after AS uuid), CAST(:limit AS integer))"
                        ),
                        {"id": invitation_id, "after": after, "limit": limit},
                    )
                ).all()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return tuple(
            AccountInvitationSummary(
                invitation_id=row[0],
                delivery=row[1],
                email=row[2],
                max_organizations=row[3],
                status=row[4],
                expired=row[5],
                revision=row[6],
                delivery_status=row[7],
                invited_by_principal_id=row[8],
                native_identity_id=row[9],
                entitlement_id=row[10],
                organizations_created=row[11],
                created_at=row[12],
                expires_at=row[13],
                accepted_at=row[14],
                revoked_at=row[15],
            )
            for row in rows
        )


def _require(actor: PlatformActorContext, capability: str) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(capability):
        raise AccountInvitationForbidden(capability)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raise_mapped(exc: DBAPIError) -> Never:
    error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
    if error_type is None:
        raise exc
    raise error_type() from None
