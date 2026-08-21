from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    SearchOfferingsQuery,
    search_offerings,
)
from request_engine.platform.db.session import SessionFactory

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _other_location(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Other clinic', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"other-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_catalog_can_discover_cardiology_for_effective_location_with_base_terms(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    reader = PostgresOfferingCatalogReader(session_factory)

    result = await search_offerings(
        reader,
        SearchOfferingsQuery(
            organization_id=scenario.organization_id,
            search_text="cardiology",
            bookable=True,
            location_id=scenario.location_id,
            effective_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        ),
    )

    assert len(result) == 1
    version = result[0].latest_version
    assert version.id == scenario.offering_version_id
    assert version.amount == Decimal("3500.000000")
    assert version.currency == "DOP"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_catalog_location_filter_does_not_advertise_unassigned_supply(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    other_location_id = _other_location(admin_conn, scenario.organization_id)
    reader = PostgresOfferingCatalogReader(session_factory)

    result = await search_offerings(
        reader,
        SearchOfferingsQuery(
            organization_id=scenario.organization_id,
            search_text="cardiology",
            location_id=other_location_id,
            effective_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        ),
    )

    assert result == ()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_catalog_location_filter_respects_assignment_effective_time(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    reader = PostgresOfferingCatalogReader(session_factory)

    result = await search_offerings(
        reader,
        SearchOfferingsQuery(
            organization_id=scenario.organization_id,
            search_text="cardiology",
            location_id=scenario.location_id,
            effective_at=datetime(2025, 12, 31, 23, 0, tzinfo=UTC),
        ),
    )

    assert result == ()
