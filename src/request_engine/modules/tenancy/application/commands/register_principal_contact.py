"""`staff.manage_own_admin_contact` registration command (docs/v3/38 §9.2).

A staff principal registers its OWN administrative contact. The API edge
enforces principal identity and kind; this layer only normalizes the contact
value with the tenancy-owned party contact normalization.
"""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.staff_contacts import PrincipalContact
from request_engine.modules.tenancy.domain.party_identity import normalize_party_contact_value


@dataclass(frozen=True, slots=True)
class RegisterPrincipalContactCommand:
    organization_id: UUID
    principal_id: UUID
    channel: str
    value: str
    idempotency_key: str


class RegisterPrincipalContactHandler(Protocol):
    async def register_principal_contact(
        self, command: RegisterPrincipalContactCommand
    ) -> PrincipalContact: ...


async def register_principal_contact(
    handler: RegisterPrincipalContactHandler,
    command: RegisterPrincipalContactCommand,
) -> PrincipalContact:
    """Validate and normalize the command, then delegate to the handler."""

    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    try:
        normalized = normalize_party_contact_value(command.channel, command.value)
    except ValueError as error:
        raise ValueError(f"contact {command.value!r}: {error}") from None
    return await handler.register_principal_contact(replace(command, value=normalized))
