"""Command factories and row readers for the staff contact PostgreSQL proofs.

Only valid prerequisites are created directly: the organization/operator
world comes from the shared S0b builder; the contact, its pending code state
and the outbox event are durable outcomes of the real staff commands.
"""

from typing import Any, cast
from uuid import UUID, uuid4

from request_engine.modules.tenancy.adapters.db.principal_contact_commands import (
    PostgresPrincipalContactCommands,
)
from request_engine.modules.tenancy.application.commands import (
    confirm_principal_contact,
    register_principal_contact,
    request_principal_contact_verification,
)
from request_engine.modules.tenancy.contracts.staff_contacts import PrincipalContact
from request_engine.platform.db.session import SessionFactory

from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world

EVENT_TYPE = "staff.contact_verification_requested.v1"
CHANNEL = "whatsapp"
VALUE = "+1 809 555 0142"


def staff_commands(session_factory: SessionFactory) -> PostgresPrincipalContactCommands:
    return PostgresPrincipalContactCommands(session_factory)


def register_command(world: PartyRegistryWorld, *, key: str | None = None):
    return register_principal_contact.RegisterPrincipalContactCommand(
        organization_id=world.organization_id,
        principal_id=world.operator_principal_id,
        channel=CHANNEL,
        value=VALUE,
        idempotency_key=key or f"register-{uuid4().hex}",
    )


def request_command(world: PartyRegistryWorld, contact_id: UUID, *, key: str):
    return request_principal_contact_verification.RequestPrincipalContactVerificationCommand(
        organization_id=world.organization_id,
        principal_id=world.operator_principal_id,
        contact_id=contact_id,
        idempotency_key=key,
    )


def confirm_command(world: PartyRegistryWorld, contact_id: UUID, code: str, *, key: str):
    return confirm_principal_contact.ConfirmPrincipalContactCommand(
        organization_id=world.organization_id,
        principal_id=world.operator_principal_id,
        contact_id=contact_id,
        code=code,
        idempotency_key=key,
    )


async def world_with_registered_contact(
    admin_conn: PgConnection, session_factory: SessionFactory
) -> tuple[PartyRegistryWorld, PostgresPrincipalContactCommands, PrincipalContact]:
    world = create_party_registry_world(admin_conn, prefix="s0b-staff")
    commands = staff_commands(session_factory)
    contact = await commands.register_principal_contact(register_command(world))
    return world, commands, contact


def staff_row(conn: PgConnection, organization_id: UUID, contact_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT verified, active, verification_code_hash, verification_expires_at,"
        " verification_attempts FROM request_engine.principal_contacts"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, contact_id),
    ).fetchone()
    assert row is not None
    return row


def outbox_codes(conn: PgConnection, organization_id: UUID) -> list[str]:
    rows = conn.execute(
        "SELECT payload FROM request_engine.outbox_messages"
        " WHERE organization_id = %s AND event_type = %s ORDER BY created_at",
        (organization_id, EVENT_TYPE),
    ).fetchall()
    payloads = cast("list[dict[str, object]]", [row[0] for row in rows])
    return [cast(str, payload["code"]) for payload in payloads]
