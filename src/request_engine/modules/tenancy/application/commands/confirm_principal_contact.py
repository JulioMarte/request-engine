"""`staff.confirm_own_admin_contact` command (docs/v3/38 §9.2).

The handler row-locks the contact and validates the one-time code: already
verified is an idempotent success without a code check; expired, exhausted
and mismatched codes map to typed errors. Success flips `verified = true`
monotonically and clears the code state. No outbox event.
"""

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.staff_contacts import PrincipalContact


@dataclass(frozen=True, slots=True)
class ConfirmPrincipalContactCommand:
    organization_id: UUID
    principal_id: UUID
    contact_id: UUID
    code: str
    idempotency_key: str


class ConfirmPrincipalContactHandler(Protocol):
    async def confirm_principal_contact(
        self, command: ConfirmPrincipalContactCommand
    ) -> PrincipalContact: ...


async def confirm_principal_contact(
    handler: ConfirmPrincipalContactHandler,
    command: ConfirmPrincipalContactCommand,
) -> PrincipalContact:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    code = command.code.strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError("code must be exactly 6 digits")
    return await handler.confirm_principal_contact(replace(command, code=code))
