"""I-S0b-3: shared family numbers are multi-match; lookups return every binding.

Two Parties are registered through the real `parties.register` command with
the same whatsapp number written in different Dominican local formats and
distinct cédulas. Phone lookup returns BOTH parties (family reality), the
name prefix returns exactly the matching parties, and the cédula exact-matches
exactly one. Expected outcomes come from the registration inputs, not from
the lookup implementation.
"""

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    register_party,
)
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    lookup_parties,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

_SHARED_PHONE = "809 555 0100"


@pytest.mark.asyncio
async def test_shared_phone_lookup_returns_every_bound_party(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-lookup")
    commands = registry_commands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    jose = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="José Pérez",
            whatsapp=_SHARED_PHONE,
            cedula="402-1234567-8",
        ),
    )
    maria = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Maria Perez",
            whatsapp="(809) 555-0100",
            cedula="402-9999999-9",
        ),
    )

    by_phone = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.PHONE,
            value="+1 (809) 555 0100",
        ),
    )
    assert {party.party_id for party in by_phone} == {jose.party_id, maria.party_id}
    assert all(
        contact.verified and contact.source_kind is PartySourceKind.OPERATOR
        for party in by_phone
        for contact in party.contact_points
    )
    assert {contact.normalized_value for party in by_phone for contact in party.contact_points} == {
        "+18095550100"
    }

    by_name = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.NAME,
            value="JOS",
        ),
    )
    assert [party.party_id for party in by_name] == [jose.party_id]

    by_document = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.DOCUMENT,
            value="402-9999999-9",
        ),
    )
    assert [party.party_id for party in by_document] == [maria.party_id]
    documents = [(d.kind, d.normalized_value) for d in by_document[0].documents]
    assert documents == [("cedula", "40299999999")]
