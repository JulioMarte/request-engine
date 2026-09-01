"""`parties.deactivate_contact_point` proofs on real PostgreSQL.

Deactivating a verified contact point must succeed WITHOUT touching
`verified` — the I-S0b-4 monotonicity guard is not tripped — and the party
must drop out of phone lookup while the other holder of the shared number
stays visible.
"""

from uuid import UUID, uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.application.commands import (
    deactivate_party_contact_point,
    register_party,
)
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    lookup_parties,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection, contact_point_row
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _deactivate_point_command(
    organization_id: UUID, principal_id: UUID, party_id: UUID, contact_point_id: UUID
) -> deactivate_party_contact_point.DeactivatePartyContactPointCommand:
    return deactivate_party_contact_point.DeactivatePartyContactPointCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        contact_point_id=contact_point_id,
        idempotency_key=f"deactivate-cp-{uuid4().hex}",
    )


@pytest.mark.asyncio
async def test_contact_point_deactivation_drops_only_that_party_from_phone_lookup(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-cpdeact")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    jose = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Jose",
            whatsapp="809 555 0400",
        ),
    )
    maria = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Maria",
            whatsapp="(809) 555-0400",
        ),
    )

    deactivated = await deactivate_party_contact_point.deactivate_party_contact_point(
        commands,
        _deactivate_point_command(
            world.organization_id,
            world.operator_principal_id,
            jose.party_id,
            jose.contact_points[0].contact_point_id,
        ),
    )

    assert deactivated.contact_point_id == jose.contact_points[0].contact_point_id
    found = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.PHONE,
            value="+1 809 555 0400",
        ),
    )
    assert [party.party_id for party in found] == [maria.party_id]


@pytest.mark.asyncio
async def test_contact_point_deactivation_never_trips_the_verification_guard(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-guardok")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Beto Uso",
            whatsapp="809 555 0500",
        ),
    )
    contact = party.contact_points[0]
    assert contact.verified

    deactivated = await deactivate_party_contact_point.deactivate_party_contact_point(
        commands,
        _deactivate_point_command(
            world.organization_id,
            world.operator_principal_id,
            party.party_id,
            contact.contact_point_id,
        ),
    )

    assert deactivated.verified is True
    verified, source_kind, active = contact_point_row(
        admin_conn, world.organization_id, contact.contact_point_id
    )
    assert (verified, source_kind, active) == (True, "operator", False)
