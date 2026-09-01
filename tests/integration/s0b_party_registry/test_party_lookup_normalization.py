"""FIX-A lookup regressions: dual-channel dedupe and stored-side accent folding.

Both cases register parties through the real `parties.register` command and
read through the real `parties.lookup` reader:

- one party holding the SAME normalized number on both `phone` and
  `whatsapp` must appear exactly once in a phone lookup (SELECT DISTINCT),
  while both contact points stay visible in the returned view;
- name lookup folds accents AND whitespace runs on the stored side, so a
  stored "José Núñez-Pérez" is found by prefix "jose nunez", "JOSE" and
  "jose  nunez"; "nunez" (not a prefix) must not match.

Expected outcomes come from the registration inputs, not from the lookup
implementation.
"""

from uuid import UUID

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
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_dual_channel_party_matches_exactly_once(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-dual")
    reader = PostgresPartyLookupReader(app_session_factory)
    party = await register_party(
        registry_commands(app_session_factory),
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Duo Canal",
            whatsapp="809 555 0122",
            phone="+1 (809) 555-0122",
            cedula="402-8888888-8",
        ),
    )

    by_phone = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.PHONE,
            value="+1 809 555 0122",
        ),
    )
    assert [entry.party_id for entry in by_phone] == [party.party_id]
    assert {contact.channel for contact in by_phone[0].contact_points} == {
        "phone",
        "whatsapp",
    }
    assert {contact.normalized_value for contact in by_phone[0].contact_points} == {"+18095550122"}


@pytest.mark.asyncio
async def test_name_lookup_folds_accents_and_whitespace(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-accent")
    reader = PostgresPartyLookupReader(app_session_factory)
    party = await register_party(
        registry_commands(app_session_factory),
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="José Núñez-Pérez",
            cedula="402-6666666-6",
        ),
    )

    async def matched_ids(value: str) -> list[UUID]:
        parties = await lookup_parties(
            reader,
            PartyLookupQuery(
                organization_id=world.organization_id,
                mode=PartyLookupMode.NAME,
                value=value,
            ),
        )
        return [entry.party_id for entry in parties]

    assert await matched_ids("jose nunez") == [party.party_id]
    assert await matched_ids("JOSE") == [party.party_id]
    assert await matched_ids("jose  nunez") == [party.party_id]
    assert await matched_ids("nunez") == []
