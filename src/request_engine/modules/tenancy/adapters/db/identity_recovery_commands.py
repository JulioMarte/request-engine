import contextlib
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.identity_recovery import (
    IDENTITY_RECOVERY_APPROVE_CAPABILITY,
    IDENTITY_RECOVERY_CAPABILITY,
    ApproveIdentityRecoveryCaseCommand,
    CreateIdentityRecoveryCaseCommand,
    IdentityRecoveryConflict,
    IdentityRecoveryError,
    IdentityRecoveryForbidden,
    IdentityRecoveryInvalid,
    IdentityRecoveryNotFound,
    IdentityRecoveryRevisionConflict,
    IdentityRecoveryUnavailable,
    IssueIdentityRecoveryCaseCommand,
    RevokeIdentityRecoveryCaseCommand,
)
from request_engine.modules.tenancy.application.queries.identity_recovery import (
    IdentityRecoveryCaseView,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.secrets.delivery import RecoverySecretDelivery
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.platform_context import PlatformActorContext

_DATABASE_ERRORS: dict[str, type[IdentityRecoveryError]] = {
    "28000": IdentityRecoveryForbidden,
    "42501": IdentityRecoveryForbidden,
    "P0002": IdentityRecoveryNotFound,
    "40001": IdentityRecoveryRevisionConflict,
    "40P01": IdentityRecoveryRevisionConflict,
    "23505": IdentityRecoveryConflict,
    "23514": IdentityRecoveryConflict,
    "55000": IdentityRecoveryConflict,
    "22023": IdentityRecoveryInvalid,
}
_PROOF_TTL = timedelta(minutes=30)


class PostgresIdentityRecoveryCommands:
    """Govern recovery cases; the proof is staged outside authoritative locks."""

    def __init__(
        self,
        session_factory: SessionFactory,
        delivery: RecoverySecretDelivery | None,
    ) -> None:
        self._session_factory = session_factory
        self._delivery = delivery

    async def create_case(
        self,
        actor: PlatformActorContext,
        command: CreateIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView:
        _authorize(actor, IDENTITY_RECOVERY_CAPABILITY)
        intent_digest = _intent_digest(
            {
                "target_native_identity_id": str(command.target_native_identity_id),
                "reason_code": command.normalized_reason_code,
                "evidence_reference": command.normalized_evidence_reference,
                "destination_reference": command.normalized_destination_reference,
            }
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.create_identity_recovery_case(
                            CAST(:case_id AS uuid),
                            CAST(:target AS uuid),
                            CAST(:reason AS text),
                            CAST(:evidence AS text),
                            CAST(:destination AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "case_id": uuid4(),
                            "target": command.target_native_identity_id,
                            "reason": command.normalized_reason_code,
                            "evidence": command.normalized_evidence_reference,
                            "destination": command.normalized_destination_reference,
                            "key_digest": _key_digest(command.idempotency_key),
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _materialize(row)

    async def approve_case(
        self,
        actor: PlatformActorContext,
        command: ApproveIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView:
        _authorize(actor, IDENTITY_RECOVERY_APPROVE_CAPABILITY)
        intent_digest = _intent_digest(
            {
                "case_id": str(command.case_id),
                "reason_code": command.normalized_reason_code,
            }
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.approve_identity_recovery_case(
                            CAST(:case_id AS uuid),
                            CAST(:expected_revision AS bigint),
                            CAST(:reason AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "case_id": command.case_id,
                            "expected_revision": command.expected_revision,
                            "reason": command.normalized_reason_code,
                            "key_digest": _key_digest(command.idempotency_key),
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _materialize(row)

    async def issue_case(
        self,
        actor: PlatformActorContext,
        command: IssueIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView:
        _authorize(actor, IDENTITY_RECOVERY_CAPABILITY)
        delivery = self._delivery
        if delivery is None:
            raise IdentityRecoveryUnavailable("recovery secret delivery is not configured")
        key_digest = _key_digest(command.idempotency_key)
        intent_digest = _intent_digest(
            {
                "case_id": str(command.case_id),
                "expected_revision": command.expected_revision,
            }
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                prepared = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.prepare_identity_recovery_issue(
                            CAST(:case_id AS uuid),
                            CAST(:expected_revision AS bigint),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "case_id": command.case_id,
                            "expected_revision": command.expected_revision,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        prepared_columns = tuple(prepared)
        if bool(prepared_columns[0]):
            return _materialize(prepared_columns[1:])
        generation = int(prepared_columns[6]) + 1
        token = issue_opaque_token()
        proof_expires_at = datetime.now(UTC) + _PROOF_TTL
        staged = await delivery.stage(
            case_id=command.case_id,
            generation=generation,
            secret=token.raw_token,
            expires_at=proof_expires_at,
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.issue_identity_recovery_case(
                            CAST(:case_id AS uuid),
                            CAST(:expected_revision AS bigint),
                            CAST(:generation AS integer),
                            CAST(:recovery_id AS uuid),
                            CAST(:token_digest AS bytea),
                            CAST(:token_fingerprint AS text),
                            CAST(:proof_expires_at AS timestamptz),
                            CAST(:ticket_id AS uuid),
                            CAST(:secret_reference AS text),
                            CAST(:secret_digest AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "case_id": command.case_id,
                            "expected_revision": command.expected_revision,
                            "generation": generation,
                            "recovery_id": token.token_id,
                            "token_digest": token.digest,
                            "token_fingerprint": token.fingerprint,
                            "proof_expires_at": staged.expires_at,
                            "ticket_id": uuid4(),
                            "secret_reference": staged.reference,
                            "secret_digest": staged.digest,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            await _discard_staged(delivery, command.case_id, generation)
            _raise_mapped(exc)
        except Exception:
            await _discard_staged(delivery, command.case_id, generation)
            raise
        return _materialize(row)

    async def revoke_case(
        self,
        actor: PlatformActorContext,
        command: RevokeIdentityRecoveryCaseCommand,
    ) -> IdentityRecoveryCaseView:
        _authorize(actor, IDENTITY_RECOVERY_CAPABILITY)
        intent_digest = _intent_digest(
            {
                "case_id": str(command.case_id),
                "reason_code": command.normalized_reason_code,
            }
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.revoke_identity_recovery_case(
                            CAST(:case_id AS uuid),
                            CAST(:expected_revision AS bigint),
                            CAST(:reason AS text),
                            CAST(:key_digest AS text),
                            CAST(:intent_digest AS text)
                        )
                        """),
                        {
                            "case_id": command.case_id,
                            "expected_revision": command.expected_revision,
                            "reason": command.normalized_reason_code,
                            "key_digest": _key_digest(command.idempotency_key),
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return _materialize(row)


def _authorize(actor: PlatformActorContext, capability: str) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(capability):
        raise IdentityRecoveryForbidden(capability)


def _key_digest(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()


def _intent_digest(intent: dict[str, object]) -> str:
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raise_mapped(exc: DBAPIError) -> NoReturn:
    error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
    if error_type is None:
        raise exc
    raise error_type() from None


async def _discard_staged(
    delivery: RecoverySecretDelivery,
    case_id: UUID,
    generation: int,
) -> None:
    with contextlib.suppress(Exception):
        await delivery.discard(case_id=case_id, generation=generation)


def _materialize(row: Sequence[Any]) -> IdentityRecoveryCaseView:
    return IdentityRecoveryCaseView(
        case_id=UUID(str(row[0])),
        target_native_identity_id=UUID(str(row[1])),
        status=str(row[2]),
        delivery_status=str(row[3]),
        revision=int(row[4]),
        issuance_generation=int(row[5]),
        approval_expires_at=row[6],
        proof_expires_at=row[7],
        created_at=row[8],
        approved_at=row[9],
        issued_at=row[10],
        consumed_at=row[11],
        revoked_at=row[12],
    )
