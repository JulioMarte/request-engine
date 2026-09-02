from dataclasses import replace

import psycopg
import pytest

from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_register_idempotency_distinguishes_party_kind(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0d-kind-idempotency")
    commands = registry_commands(app_session_factory)
    person_command = register_command(
        world.organization_id,
        world.operator_principal_id,
        display_name="Entidad ambigua",
    )
    person_command = replace(person_command, idempotency_key="stable-party-kind")
    organization_command = replace(person_command, party_kind=PartyKind.ORGANIZATION)

    created = await register_party(commands, person_command)
    assert created.party_kind == PartyKind.PERSON.value
    with pytest.raises(IdempotencyConflict):
        await register_party(commands, organization_command)

    rows = admin_conn.execute(
        "SELECT party_kind FROM request_engine.parties "
        "WHERE organization_id = %s AND display_name = %s",
        (world.organization_id, "Entidad ambigua"),
    ).fetchall()
    assert rows == [(PartyKind.PERSON.value,)]


def test_party_kind_is_immutable_in_postgresql(admin_conn: PgConnection) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0d-kind-immutable")
    party_id = admin_conn.execute(
        "INSERT INTO request_engine.parties (organization_id, party_kind, display_name) "
        "VALUES (%s, 'person', 'Immutable Party') RETURNING id",
        (world.organization_id,),
    ).fetchone()
    assert party_id is not None

    with pytest.raises(psycopg.errors.CheckViolation):
        with admin_conn.transaction():
            admin_conn.execute(
                "UPDATE request_engine.parties SET party_kind = 'organization' "
                "WHERE organization_id = %s AND id = %s",
                (world.organization_id, party_id[0]),
            )
