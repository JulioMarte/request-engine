"""Confirm-path world builders and command factories for the S0b proofs.

Only valid prerequisites are created directly: since §9.2 no creation command
produces `verified = false`, the secondhand-number world is seeded as a
business-plausible prerequisite; the confirm command under test owns the flip.
"""

from typing import cast
from uuid import UUID

from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartySourceKind,
    RegisteredParty,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world


def confirm_command(
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    contact_point_id: UUID,
    *,
    key: str,
) -> ConfirmPartyContactPointCommand:
    return ConfirmPartyContactPointCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        contact_point_id=contact_point_id,
        idempotency_key=key,
    )


def confirm_key(contact_point_id: UUID) -> str:
    return f"confirm-{contact_point_id.hex}"


async def subject_registered_contact_point(
    admin_conn: PgConnection, session_factory: SessionFactory
) -> tuple[PartyRegistryWorld, RegisteredParty, PartyContactPoint]:
    """Subject world: a self-provided contact point via the real register command."""

    world = create_party_registry_world(admin_conn, prefix="s0b-confirm")
    party = await register_party(
        registry_commands(session_factory),
        register_command(
            world.organization_id,
            world.bot_principal_id,
            display_name="Paciente Bot",
            whatsapp="+1 809 555 0110",
            source_kind=PartySourceKind.SUBJECT,
        ),
    )
    return world, party, party.contact_points[0]


async def secondhand_unverified_contact_point(
    admin_conn: PgConnection, session_factory: SessionFactory
) -> tuple[PartyRegistryWorld, RegisteredParty, PartyContactPoint]:
    """Secondhand-information world: one unverified contact point."""

    world, party, _ = await subject_registered_contact_point(admin_conn, session_factory)
    row = admin_conn.execute(
        "INSERT INTO request_engine.party_contact_points"
        " (organization_id, party_id, channel, normalized_value, verified, source_kind,"
        "  created_by_principal_id)"
        " VALUES (%s, %s, 'phone', '+18095550177', false, 'subject', %s) RETURNING id",
        (world.organization_id, party.party_id, world.bot_principal_id),
    ).fetchone()
    assert row is not None
    contact = PartyContactPoint(
        party_id=party.party_id,
        contact_point_id=cast(UUID, row[0]),
        channel="phone",
        normalized_value="+18095550177",
        verified=False,
        source_kind=PartySourceKind.SUBJECT,
    )
    return world, party, contact


async def verified_operator_contact_point(
    admin_conn: PgConnection, session_factory: SessionFactory
) -> tuple[PartyRegistryWorld, RegisteredParty, PartyContactPoint]:
    """Operator world: a verified contact point via the real register command."""

    world = create_party_registry_world(admin_conn, prefix="s0b-guard")
    party = await register_party(
        registry_commands(session_factory),
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Paciente Mostrador",
            whatsapp="+1 809 555 0199",
        ),
    )
    return world, party, party.contact_points[0]
