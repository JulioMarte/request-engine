from request_engine.modules.tenancy.adapters.db.identity_exchange_adopt import (
    PostgresPortableIdentityAdopter,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_match import (
    PostgresPortableIdentityMatcher,
)
from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_administrative_identifier as admin_identifier_commands,
    add_party_document,
    register_party,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    publish_portable_profile,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adapters, operator_actor, publish_command
from ._party_administrative_identifier_support import identifier_command
from ._party_commands import document_command, register_command
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world


async def published_source(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    *,
    value: str,
    kind: str = "cedula",
    authority: str | None = None,
) -> tuple[
    PartyRegistryWorld,
    RegisteredParty,
    PostgresPortableIdentityMatcher,
    PostgresPortableIdentityAdopter,
]:
    world = create_party_registry_world(admin_conn, prefix="s0d-source")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="María Gómez",
            phone="809-555-1212",
            cedula=value if kind == "cedula" else None,
        ),
    )
    if kind != "cedula":
        await add_party_document.add_party_document(
            commands,
            document_command(
                world.organization_id,
                world.operator_principal_id,
                party.party_id,
                kind,
                value,
                authority=authority,
            ),
        )
    await admin_identifier_commands.add_party_administrative_identifier(
        commands,
        identifier_command(
            world.organization_id,
            world.operator_principal_id,
            party.party_id,
        ),
    )
    publisher, matcher, adopter = adapters(app_session_factory)
    with operator_actor(world.organization_id, world.operator_principal_id):
        await publish_portable_profile(
            publisher,
            publish_command(
                world.organization_id,
                world.operator_principal_id,
                party.party_id,
                kind=kind,
                authority=authority,
            ),
        )
    return world, party, matcher, adopter
