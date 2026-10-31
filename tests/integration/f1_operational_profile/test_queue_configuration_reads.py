from typing import Any, TypedDict
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.modules.queue.adapters.db.configuration_reader import (
    PostgresServiceQueueConfigurationReader,
)
from request_engine.modules.queue.adapters.db.service_queue_creation_commands import (
    PostgresServiceQueueCreationCommands,
)
from request_engine.modules.queue.api.configuration_router import create_configuration_router
from request_engine.modules.queue.application.commands.create_service_queue import (
    CreateServiceQueueCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired
from request_engine.platform.security.principal_authority import CapabilityRequired

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.integration]


class _ReadAuthority(TypedDict):
    principal_id: UUID
    authority_party_id: UUID


def _grant(conn: Connection[Any], world: F1ContextualScenario) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id,"
        "principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational','queue.read_configuration',%s,"
        "'operator','queue configuration read')",
        (world.organization_id, world.principal_id, world.principal_id),
    )


async def _create(factory: SessionFactory, world: F1ContextualScenario, label: str) -> UUID:
    state = await PostgresServiceQueueCreationCommands(factory).create_service_queue(
        CreateServiceQueueCommand(
            world.organization_id,
            world.principal_id,
            world.authority_party_id,
            world.location_id,
            None,
            f"reception-{uuid4().hex}",
            label,
            f"configure-{uuid4().hex}",
        )
    )
    return state.queue_id


@pytest.mark.asyncio
async def test_runtime_queue_configuration_read_checks_current_grant_and_exact_party(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    queue = await _create(app_session_factory, world, "Walk-in reception")
    foreign = await _create(app_session_factory, other, "Foreign reception")
    reader = PostgresServiceQueueConfigurationReader(app_session_factory)
    args: _ReadAuthority = {
        "principal_id": world.principal_id,
        "authority_party_id": world.authority_party_id,
    }
    with pytest.raises(CapabilityRequired):
        await reader.read_queue_configuration(world.organization_id, **args)
    _grant(admin_conn, world)
    rows = await reader.read_queue_configuration(world.organization_id, **args)
    assert len(rows) == 1
    assert rows[0].queue_id == queue and rows[0].revision == 1
    assert rows[0].location_id == world.location_id and rows[0].policy_key == "fifo"
    assert rows[0].display_name == "Walk-in reception" and rows[0].active
    assert (
        await reader.read_queue_configuration(world.organization_id, queue_id=foreign, **args) == ()
    )
    # Inactive configuration is a valid pre-existing administrative fact;
    # reading it must not silently reuse the public active-only catalogue.
    admin_conn.execute(
        "UPDATE request_engine.service_queues SET active=false WHERE id=%s",
        (queue,),
    )
    inactive = await reader.read_queue_configuration(world.organization_id, **args)
    assert len(inactive) == 1 and inactive[0].queue_id == queue and not inactive[0].active
    with pytest.raises(OperationalAuthorityRequired):
        await reader.read_queue_configuration(
            world.organization_id,
            principal_id=world.principal_id,
            authority_party_id=other.authority_party_id,
        )
    admin_conn.execute(
        "UPDATE request_engine.representations SET status='revoked' "
        "WHERE organization_id=%s AND principal_id=%s AND scope_key='operations.manage_supply'",
        (world.organization_id, world.principal_id),
    )
    with pytest.raises(OperationalAuthorityRequired):
        await reader.read_queue_configuration(world.organization_id, **args)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), "
        "revoked_by_principal_id=principal_id "
        "WHERE organization_id=%s AND principal_id=%s "
        "AND capability_key='queue.read_configuration'",
        (world.organization_id, world.principal_id),
    )
    with pytest.raises(CapabilityRequired):
        await reader.read_queue_configuration(world.organization_id, **args)


class _Actor:
    def __init__(self, world: F1ContextualScenario) -> None:
        self.current = ActorContext(
            world.organization_id, world.principal_id, frozenset({"queue.read_configuration"})
        )

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.current


@pytest.mark.asyncio
async def test_http_queue_configuration_pages_use_runtime_read_and_foreign_ids_remain_opaque(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    ids = sorted(
        [
            await _create(app_session_factory, world, "Reception A"),
            await _create(app_session_factory, world, "Reception B"),
        ]
    )
    foreign = await _create(app_session_factory, other, "Foreign reception")
    _grant(admin_conn, world)
    app = FastAPI()
    app.include_router(
        create_configuration_router(
            PostgresServiceQueueConfigurationReader(app_session_factory), _Actor(world)
        )
    )
    query = {"authority_party_id": str(world.authority_party_id), "limit": "1"}
    path = "/v1/queues/configuration"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(path, params=query)
        assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
        assert [item["queue_id"] for item in first.json()["items"]] == [str(ids[0])]
        assert first.json()["next_cursor"] == str(ids[0])
        second = await client.get(path, params={**query, "cursor": first.json()["next_cursor"]})
        assert second.status_code == 200
        assert [item["queue_id"] for item in second.json()["items"]] == [str(ids[1])]
        assert second.json()["next_cursor"] is None
        detail_params = {"authority_party_id": str(world.authority_party_id)}
        detail = await client.get(f"{path}/{ids[0]}", params=detail_params)
        assert detail.status_code == 200 and detail.json()["revision"] == 1
        for absent_id in [foreign, uuid4()]:
            missing = await client.get(f"{path}/{absent_id}", params=detail_params)
            assert missing.status_code == 404 and missing.json() == {
                "detail": "ServiceQueue not found"
            }
        assert (await client.get(path, params={**query, "limit": "101"})).status_code == 422
        assert (await client.get(path, params={**query, "cursor": "invalid"})).status_code == 422
        assert (
            await client.get(path, params={**query, "organization_id": str(other.organization_id)})
        ).status_code == 422
    count = admin_conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries WHERE organization_id=%s",
        (world.organization_id,),
    ).fetchone()
    assert count is not None and count[0] == 0
