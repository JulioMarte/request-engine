"""PostgreSQL staff contact confirmation adapter (docs/v3/38 §9.2).

One transaction: row-lock the principal's own contact; already-verified is
an idempotent success without a code check; otherwise expired -> exhausted ->
hash validation. Success flips `verified` monotonically (0025 guard
backstops this) and clears the code state. No outbox event.
"""

from datetime import UTC, datetime
from typing import cast

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.principal_contact_codec import (
    contact_from_json,
    contact_from_row,
    contact_to_json,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_support import (
    bump_attempts,
    code_hash,
    lock_contact,
    mark_verified,
)
from request_engine.modules.tenancy.application.commands import confirm_principal_contact
from request_engine.modules.tenancy.application.errors import (
    VerificationAttemptsExhausted,
    VerificationCodeExpired,
    VerificationCodeInvalid,
)
from request_engine.modules.tenancy.contracts.staff_contacts import PrincipalContact
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "staff.confirm_own_admin_contact"
_MAX_ATTEMPTS = 5


class PostgresPrincipalContactConfirmationCommands:
    """Idempotent monotone confirmation of one staff administrative contact."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def confirm_principal_contact(
        self, command: confirm_principal_contact.ConfirmPrincipalContactCommand
    ) -> PrincipalContact:
        fingerprint = command_fingerprint(_CAPABILITY, {"contact_id": str(command.contact_id)})
        contact: PrincipalContact | None = None
        failure: VerificationAttemptsExhausted | VerificationCodeInvalid | None = None
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return contact_from_json(cast(dict[str, object], replay["contact"]))
            row = await lock_contact(
                session, command.organization_id, command.principal_id, command.contact_id
            )
            already_verified = cast(bool, row["verified"])
            if not already_verified:
                failure = await _validate_code(session, row, command)
            if failure is None:
                if not already_verified:
                    await mark_verified(
                        session, command.organization_id, command.principal_id, command.contact_id
                    )
                    row = await lock_contact(
                        session, command.organization_id, command.principal_id, command.contact_id
                    )
                contact = contact_from_row(row)
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="PrincipalContact",
                    aggregate_id=command.contact_id,
                    idempotency_id=idempotency_id,
                    details={
                        "principal_id": str(command.principal_id),
                        "already_verified": already_verified,
                    },
                )
                await complete_idempotency(
                    session, idempotency_id, {"contact": contact_to_json(contact)}
                )
        if failure is not None:
            # The attempt increment already committed; the idempotency record
            # stays pending so the same key may retry with the right code.
            raise failure
        assert contact is not None
        return contact


async def _validate_code(
    session: AsyncSession,
    row: RowMapping,
    command: confirm_principal_contact.ConfirmPrincipalContactCommand,
) -> VerificationAttemptsExhausted | VerificationCodeInvalid | None:
    """Expired -> exhausted -> hash; the attempt bump commits before raising."""

    organization_id = command.organization_id
    principal_id = command.principal_id
    contact_id = command.contact_id
    expires_at = row["verification_expires_at"]
    if row["verification_code_hash"] is None or not isinstance(expires_at, datetime):
        raise VerificationCodeExpired()
    if expires_at <= datetime.now(UTC):
        raise VerificationCodeExpired()
    if int(cast(int, row["verification_attempts"])) >= _MAX_ATTEMPTS:
        raise VerificationAttemptsExhausted()
    if row["verification_code_hash"] == code_hash(command.code):
        return None
    attempts = await bump_attempts(session, organization_id, principal_id, contact_id)
    remaining = _MAX_ATTEMPTS - attempts
    if remaining <= 0:
        return VerificationAttemptsExhausted()
    return VerificationCodeInvalid(remaining)
