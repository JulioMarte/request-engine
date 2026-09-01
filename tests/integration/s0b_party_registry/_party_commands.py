"""Command factories and adapter composition for the S0b party registry proofs."""

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
    RegisteredParty,
    RegisteredVia,
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
    registered_via: RegisteredVia = RegisteredVia.OPERATOR,
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
        registered_via=registered_via,
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


async def bot_registered_contact_point(
    admin_conn: PgConnection, session_factory: SessionFactory
) -> tuple[PartyRegistryWorld, RegisteredParty, PartyContactPoint]:
    """Bot path world: an unverified contact point via the real register command."""

    world = create_party_registry_world(admin_conn, prefix="s0b-confirm")
    party = await register_party(
        registry_commands(session_factory),
        register_command(
            world.organization_id,
            world.bot_principal_id,
            display_name="Paciente Bot",
            whatsapp="+1 809 555 0110",
            registered_via=RegisteredVia.BOT,
        ),
    )
    return world, party, party.contact_points[0]


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
