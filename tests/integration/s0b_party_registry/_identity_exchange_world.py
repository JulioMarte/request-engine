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
    add_party_administrative_identifier as administrative_identifier_command,
)
from request_engine.modules.tenancy.application.commands.add_party_document import (
    add_party_document,
)
from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.application.identity_exchange import publish_portable_profile
from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.modules.tenancy.domain.party_subject_identity import party_kind_for_document
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
    party_kind = party_kind_for_document(kind)
    party = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            party_kind=party_kind,
            display_name=(
                "Acme Dominicana SRL" if party_kind is PartyKind.ORGANIZATION else "María Gómez"
            ),
            phone="809-555-1212",
            cedula=value if kind == "cedula" else None,
            rnc=value if kind == "rnc" else None,
        ),
    )
    if kind not in {"cedula", "rnc"}:
        await add_party_document(
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
    if party_kind is PartyKind.PERSON:
        await administrative_identifier_command.add_party_administrative_identifier(
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


async def publish_additional_document(
    app_session_factory: SessionFactory,
    world: PartyRegistryWorld,
    party: RegisteredParty,
    *,
    kind: str,
    value: str,
    authority: str,
) -> tuple[PostgresPortableIdentityMatcher, PostgresPortableIdentityAdopter]:
    commands = PostgresPartyRegistryCommands(app_session_factory)
    await add_party_document(
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
    return matcher, adopter
