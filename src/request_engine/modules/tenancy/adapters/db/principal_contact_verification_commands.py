"""PostgreSQL staff contact verification-request adapter (docs/v3/38 §9.2).

One transaction: row-lock the principal's own contact, generate a fresh
6-digit code, store its sha256 hash with a 15-minute expiry, reset the
attempt counter, append ONE outbox event carrying the code as durable
transactional intent (delivery is external), audit and complete the
idempotency record. Replay returns the stored contact id + expiry and never
a code.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from request_engine.modules.tenancy.adapters.db.principal_contact_codec import (
    issued_from_json,
    issued_to_json,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_support import (
    code_hash,
    lock_contact,
    new_verification_code,
    set_pending_verification,
)
from request_engine.modules.tenancy.application.commands import (
    request_principal_contact_verification,
)
from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContactVerificationIssued,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox

_CAPABILITY = "staff.manage_own_admin_contact"
_EVENT_TYPE = "staff.contact_verification_requested.v1"
_VERIFICATION_TTL = timedelta(minutes=15)


class PostgresPrincipalContactVerificationCommands:
    """Idempotent issuer of one staff contact verification challenge."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def request_principal_contact_verification(
        self,
        command: (
            request_principal_contact_verification.RequestPrincipalContactVerificationCommand
        ),
    ) -> PrincipalContactVerificationIssued:
        fingerprint = command_fingerprint(_CAPABILITY, {"contact_id": str(command.contact_id)})
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
                return issued_from_json(cast(dict[str, object], replay["issued"]))
            row = await lock_contact(
                session, command.organization_id, command.principal_id, command.contact_id
            )
            code = new_verification_code()
            expires_at = datetime.now(UTC) + _VERIFICATION_TTL
            await set_pending_verification(
                session,
                command.organization_id,
                command.principal_id,
                command.contact_id,
                code_hash(code),
                expires_at,
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type=_EVENT_TYPE,
                aggregate_kind="PrincipalContact",
                aggregate_id=command.contact_id,
                payload={
                    "principal_id": str(command.principal_id),
                    "contact_id": str(command.contact_id),
                    "channel": row["channel"],
                    "normalized_value": row["normalized_value"],
                    "code": code,
                },
            )
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
                    "channel": row["channel"],
                    "expires_at": expires_at.isoformat(),
                },
            )
            issued = PrincipalContactVerificationIssued(
                contact_id=command.contact_id, expires_at=expires_at
            )
            await complete_idempotency(session, idempotency_id, {"issued": issued_to_json(issued)})
            return issued
