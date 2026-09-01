"""`staff.manage_own_admin_contact` verification-request command (docs/v3/38 §9.2).

The handler generates the one-time code, stores it hashed with a 15-minute
expiry, resets the attempt counter and appends ONE outbox event carrying the
code as durable transactional intent (delivery is external) — all inside the
authoritative transaction. Idempotent replay returns the stored result
WITHOUT regenerating the code and never exposes a stale code.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContactVerificationIssued,
)


@dataclass(frozen=True, slots=True)
class RequestPrincipalContactVerificationCommand:
    organization_id: UUID
    principal_id: UUID
    contact_id: UUID
    idempotency_key: str


class RequestPrincipalContactVerificationHandler(Protocol):
    async def request_principal_contact_verification(
        self, command: RequestPrincipalContactVerificationCommand
    ) -> PrincipalContactVerificationIssued: ...


async def request_principal_contact_verification(
    handler: RequestPrincipalContactVerificationHandler,
    command: RequestPrincipalContactVerificationCommand,
) -> PrincipalContactVerificationIssued:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.request_principal_contact_verification(command)
