from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.adapters.db.onboarding_reader import (
    PostgresCatalogOnboardingReader,
)
from request_engine.modules.catalog.application.queries.search_offerings import SearchOfferingsQuery
from request_engine.platform.db.session import SessionFactory

from .dummy_data import create_contextual_cardiology_scenario

pytestmark = [pytest.mark.postgres, pytest.mark.adversarial, pytest.mark.integration]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latest_bookable,active,expected", [(False, True, 0), (True, False, 0), (True, True, 1)]
)
async def test_catalog_readiness_counts_only_active_latest_bookable_versions(
    admin_conn: Connection[Any],
    app_session_factory: SessionFactory,
    latest_bookable: bool,
    active: bool,
    expected: int,
) -> None:
    # Historical versions are valid prerequisites, not a seeded readiness result.
    world = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    second_version_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.offering_versions "
        "(id,organization_id,offering_id,version,duration_minutes,bookable,booking_policy) "
        "SELECT %s,organization_id,offering_id,2,30,%s,booking_policy "
        "FROM request_engine.offering_versions WHERE id=%s",
        (second_version_id, latest_bookable, world.offering_version_id),
    )
    admin_conn.execute(
        "UPDATE request_engine.offerings SET active=%s WHERE organization_id=%s",
        (active, world.organization_id),
    )
    reader = PostgresCatalogOnboardingReader(app_session_factory)
    result = await reader.read_catalog_supply(organization_id=world.organization_id)
    assert result.location_count == 1
    assert result.bookable_offering_version_count == expected
    foreign = await reader.read_catalog_supply(organization_id=other.organization_id)
    assert foreign.location_count == foreign.bookable_offering_version_count == 1

    # Cross-check the existing consumer projection, through the restricted role.
    discovery = await PostgresOfferingCatalogReader(app_session_factory).search_offerings(
        SearchOfferingsQuery(world.organization_id, bookable=True)
    )
    assert len(discovery) == expected
    if expected:
        assert discovery[0].latest_version.id == second_version_id
    # A read must not rewrite or delete the historical configuration.
    assert admin_conn.execute(
        "SELECT version,bookable FROM request_engine.offering_versions "
        "WHERE organization_id=%s ORDER BY version",
        (world.organization_id,),
    ).fetchall() == [(1, True), (2, latest_bookable)]


@pytest.mark.asyncio
async def test_catalog_readiness_keeps_active_location_filter_and_empty_tenant_isolation(
    admin_conn: Connection[Any], app_session_factory: SessionFactory
) -> None:
    world = create_contextual_cardiology_scenario(admin_conn)
    admin_conn.execute(
        "UPDATE request_engine.locations SET active=false WHERE id=%s", (world.location_id,)
    )
    reader = PostgresCatalogOnboardingReader(app_session_factory)
    result = await reader.read_catalog_supply(organization_id=world.organization_id)
    assert result.location_count == 0
    assert result.bookable_offering_version_count == 1
    absent = await reader.read_catalog_supply(organization_id=uuid4())
    assert absent.location_count == absent.bookable_offering_version_count == 0
