"""Real restricted PostgreSQL inventory, current grants and Party scopes."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.catalog.adapters.db.administration_reader import (
    PostgresCatalogAdministrationReader,
)
from request_engine.modules.catalog.api.administration_router import create_administration_router
from request_engine.modules.catalog.application.queries.administration import (
    CatalogAdministrationQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired
from request_engine.platform.security.principal_authority import CapabilityRequired

from .dummy_data import create_contextual_cardiology_scenario

pytestmark = [pytest.mark.postgres, pytest.mark.adversarial, pytest.mark.security]


def grant_read(conn: Connection[Any], organization: object, principal: object) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id,"
        "principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational','catalog.read_configuration',%s,"
        "'operator','administrative read grant')",
        (organization, principal, principal),
    )


@pytest.mark.asyncio
async def test_catalog_administration_inventory_is_bounded_includes_inactive_and_latest_versions(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    grant_read(admin_conn, world.organization_id, world.principal_id)
    admin_conn.execute(
        "UPDATE request_engine.locations SET active=false,address_line1='Office 2' WHERE id=%s",
        (world.location_id,),
    )
    second_location = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.locations"
        "(id,organization_id,location_key,display_name,timezone) "
        "VALUES(%s,%s,'secondary','Secondary','UTC')",
        (second_location, world.organization_id),
    )
    offering_row = admin_conn.execute(
        "SELECT offering_id FROM request_engine.offering_versions WHERE id=%s",
        (world.offering_version_id,),
    ).fetchone()
    assert offering_row
    offering_id = offering_row[0]
    newer_version = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.offering_versions(id,organization_id,offering_id,"
        "version,duration_minutes,bookable) VALUES(%s,%s,%s,2,40,true)",
        (newer_version, world.organization_id, offering_id),
    )
    admin_conn.execute(
        "UPDATE request_engine.offerings SET active=false WHERE id=%s", (offering_id,)
    )
    reader = PostgresCatalogAdministrationReader(app_session_factory)
    query = CatalogAdministrationQuery(
        world.organization_id, world.principal_id, world.authority_party_id, limit=1
    )
    first = await reader.locations(query)
    assert len(first) == 2  # One look-ahead row; HTTP owns slicing/cursor.
    assert {row.location_id for row in first} == {world.location_id, second_location}
    last = await reader.locations(replace(query, after=first[0].location_id))
    assert len(last) == 1 and last[0].location_id == first[1].location_id
    assert await reader.locations(replace(query, after=last[0].location_id)) == ()
    target = (await reader.locations(replace(query, target_id=world.location_id)))[0]
    assert target.active is False and target.address_line1 == "Office 2"
    assert target.operational_revision > 0
    offerings = await reader.offerings(query)
    assert len(offerings) == 1 and offerings[0].offering_id == offering_id
    assert offerings[0].active is False and offerings[0].offering_version_id == newer_version
    assert offerings[0].version == 2 and offerings[0].booking_policy_revision == 0
    assert await reader.locations(replace(query, target_id=other.location_id)) == ()
    assert await reader.offerings(replace(query, target_id=uuid4())) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,scope",
    [("locations", "operations.manage_profile"), ("offerings", "operations.manage_terms")],
)
async def test_catalog_administration_current_authority_is_rechecked_under_runtime_role(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
    kind: str,
    scope: str,
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    reader = PostgresCatalogAdministrationReader(app_session_factory)
    query = CatalogAdministrationQuery(
        world.organization_id, world.principal_id, world.authority_party_id
    )
    read = getattr(reader, kind)
    with pytest.raises(CapabilityRequired):
        await read(query)
    grant_read(admin_conn, world.organization_id, world.principal_id)
    assert len(await read(query)) == 1
    with pytest.raises(OperationalAuthorityRequired):
        await read(replace(query, authority_party_id=other.authority_party_id))
    with pytest.raises(CapabilityRequired):
        await read(replace(query, principal_id=other.principal_id))
    admin_conn.execute(
        "UPDATE request_engine.representations SET status='revoked' "
        "WHERE organization_id=%s AND principal_id=%s AND scope_key=%s",
        (world.organization_id, world.principal_id, scope),
    )
    with pytest.raises(OperationalAuthorityRequired):
        await read(query)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), "
        "revoked_by_principal_id=principal_id "
        "WHERE organization_id=%s AND principal_id=%s "
        "AND capability_key='catalog.read_configuration'",
        (world.organization_id, world.principal_id),
    )
    with pytest.raises(CapabilityRequired):
        await read(query)


@pytest.mark.asyncio
async def test_catalog_inventory_http_uses_current_runtime_authority_and_foreign_opaque_reads(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    foreign = create_contextual_cardiology_scenario(admin_conn)
    grant_read(admin_conn, world.organization_id, world.principal_id)

    class Resolver:
        async def resolve_actor(self, request: Request) -> ActorContext:
            return ActorContext(
                world.organization_id,
                world.principal_id,
                frozenset({"catalog.read_configuration"}),
            )

    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(
        create_administration_router(
            PostgresCatalogAdministrationReader(app_session_factory), Resolver()
        )
    )
    params = {"authority_party_id": str(world.authority_party_id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for collection in ("locations", "offerings"):
            page = await client.get(f"/v1/catalog/{collection}/configuration", params=params)
            assert page.status_code == 200 and len(page.json()["items"]) == 1
            assert page.headers["cache-control"] == "no-store"
            assert page.json()["next_cursor"] is None
        absent_results: list[dict[str, Any]] = []
        for target in (foreign.location_id, uuid4()):
            absent = await client.get(
                f"/v1/catalog/locations/{target}/configuration", params=params
            )
            assert absent.status_code == 404
            assert absent.json()["error"]["code"] == "not_found"
            absent_results.append(absent.json())
        assert absent_results[0] == absent_results[1]
        admin_conn.execute(
            "UPDATE request_engine.principal_authority_grants SET status='revoked', "
            "revision=revision+1, revoked_at=clock_timestamp(), "
            "revoked_by_principal_id=principal_id "
            "WHERE organization_id=%s AND principal_id=%s "
            "AND capability_key='catalog.read_configuration'",
            (world.organization_id, world.principal_id),
        )
        denied = await client.get("/v1/catalog/locations/configuration", params=params)
        assert denied.status_code == 403
