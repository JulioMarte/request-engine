"""Command factories and adapter composition for the S0b party registry proofs."""

from typing import cast
from uuid import UUID, uuid4

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
    register_party,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyContactPointInput,
    PartyDocumentInput,
    PartySourceKind,
    RegisteredParty,
)
from request_engine.platform.db.session import SessionFactory

from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world


def registry_commands(session_factory: SessionFactory) -> PostgresPartyRegistryCommands:
    return PostgresPartyRegistryCommands(session_factory)


def register_command(
    organization_id: UUID,
    principal_id: UUID,
    *,
    display_name: str,
    whatsapp: str | None = None,
    phone: str | None = None,
    cedula: str | None = None,
    source_kind: PartySourceKind = PartySourceKind.OPERATOR,
) -> RegisterPartyCommand:
    contact_points: tuple[PartyContactPointInput, ...] = ()
    if whatsapp or phone:
        channels = [("whatsapp", whatsapp), ("phone", phone)]
        contact_points = tuple(
            PartyContactPointInput(channel, value)
            for channel, value in channels
            if value is not None
        )
    return RegisterPartyCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        display_name=display_name,
        source_kind=source_kind,
        idempotency_key=f"register-{uuid4().hex}",
        contact_points=contact_points,
        documents=(PartyDocumentInput("cedula", cedula),) if cedula else (),
    )


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
    """Secondhand-information world: one unverified contact point.

    Since §9.2 no creation command produces `verified = false`, so this
    business-plausible prerequisite (a secondhand number taken by phone) is
    seeded directly; the confirm command under test owns the flip.
    """

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


def confirm_key(contact_point_id: UUID) -> str:
    return f"confirm-{contact_point_id.hex}"
