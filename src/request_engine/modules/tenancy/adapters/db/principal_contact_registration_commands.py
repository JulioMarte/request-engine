"""PostgreSQL staff principal contact registration adapter (§9.2).

Idempotent insert of the principal's own administrative contact, created
`verified = false` (§9.2: staff contacts are confirmed by one-time code, not
by provenance). Duplicate contact values and the one-active-contact-per-
principal rule map to the typed conflict.
"""

from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.principal_contact_codec import (
    contact_from_json,
    contact_from_row,
    contact_to_json,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_support import insert_contact
from request_engine.modules.tenancy.application.commands import register_principal_contact
from request_engine.modules.tenancy.application.errors import PrincipalContactExists
from request_engine.modules.tenancy.contracts.staff_contacts import PrincipalContact
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "staff.manage_own_admin_contact"


class PostgresPrincipalContactRegistrationCommands:
    """Idempotent registration of one staff administrative contact."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def register_principal_contact(
        self, command: register_principal_contact.RegisterPrincipalContactCommand
    ) -> PrincipalContact:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {"channel": command.channel, "normalized_value": command.value},
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
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
                row = await insert_contact(
                    session,
                    command.organization_id,
                    command.principal_id,
                    command.channel,
                    command.value,
                )
                contact = contact_from_row(row)
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="PrincipalContact",
                    aggregate_id=contact.contact_id,
                    idempotency_id=idempotency_id,
                    details={
                        "principal_id": str(command.principal_id),
                        "channel": contact.channel,
                        "normalized_value": contact.normalized_value,
                        "verified": False,
                    },
                )
                await complete_idempotency(
                    session, idempotency_id, {"contact": contact_to_json(contact)}
                )
                return contact
        except IntegrityError as exc:
            raise PrincipalContactExists(
                command.principal_id, command.channel, command.value
            ) from exc
