from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.configuration_reader import (
    PostgresCatalogConfigurationReader,
)
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    SearchOfferingsQuery,
    search_offerings,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.principal_authority import CapabilityRequired

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


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.capacity
@pytest.mark.adversarial
@pytest.mark.parametrize(
    "capacity_model,capacity_units,extra_exclusive,eligible",
    [
        ("units", 2, False, True),
        ("exclusive", 1, True, False),
    ],
)
async def test_catalog_requirement_quantity_is_units_on_one_concrete_resource(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    capacity_model: str,
    capacity_units: int,
    extra_exclusive: bool,
    eligible: bool,
) -> None:
    # Valid configuration, not seeded output: the real SQL reader must distinguish
    # one two-unit resource from two exclusive resources for one quantity-two requirement.
    scenario = create_contextual_cardiology_scenario(
        admin_conn,
        requirement_quantity=2,
        capacity_model=capacity_model,
        capacity_units=capacity_units,
    )
    if extra_exclusive:
        row = admin_conn.execute(
            """INSERT INTO request_engine.resources (
                   organization_id, resource_key, display_name, capacity_model, capacity_units
               ) VALUES (%s, %s, 'Second doctor', 'exclusive', 1) RETURNING id""",
            (scenario.organization_id, f"doctor-{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        admin_conn.execute(
            """INSERT INTO request_engine.resource_capability_assignments (
                   organization_id, resource_id, capability_id
               ) SELECT organization_id, %s, capability_id
                   FROM request_engine.offering_resource_requirements WHERE id=%s""",
            (row[0], scenario.requirement_id),
        )
        admin_conn.execute(
            """INSERT INTO request_engine.resource_location_assignments (
                   organization_id, resource_id, location_id, effective_during
               ) VALUES (%s, %s, %s, tstzrange('2026-01-01', NULL, '[)'))""",
            (scenario.organization_id, row[0], scenario.location_id),
        )
    reader = PostgresOfferingCatalogReader(session_factory)
    results = await reader.search_offerings(
        SearchOfferingsQuery(
            organization_id=scenario.organization_id,
            location_id=scenario.location_id,
            effective_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        )
    )
    assert bool(results) is eligible
    key = admin_conn.execute(
        """SELECT o.offering_key FROM request_engine.offerings o
            JOIN request_engine.offering_versions v ON v.offering_id=o.id WHERE v.id=%s""",
        (scenario.offering_version_id,),
    ).fetchone()
    assert key is not None
    detail = await reader.get_offering_by_key(scenario.organization_id, key[0])
    assert detail is not None
    assert (scenario.location_id in (detail.eligible_location_ids or ())) is eligible


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.contract
async def test_configuration_reconstructs_requirement_policy_and_vocabulary_after_reconnect(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(
        admin_conn,
        requirement_quantity=2,
        capacity_model="units",
        capacity_units=2,
    )
    admin_conn.execute(
        """INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Nurse'), (%s, %s, 'Equipment')""",
        (
            scenario.organization_id,
            f"nurse-{uuid4().hex}",
            scenario.organization_id,
            f"equipment-{uuid4().hex}",
        ),
    )
    reader = PostgresCatalogConfigurationReader(app_session_factory)
    admin_conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id,"
        "principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational','catalog.read_configuration',%s,"
        "'operator','catalog configuration reader')",
        (scenario.organization_id, scenario.principal_id, scenario.principal_id),
    )
    configuration = await reader.read_offering_configuration(
        scenario.organization_id,
        scenario.offering_version_id,
        principal_id=scenario.principal_id,
    )
    assert configuration is not None
    assert configuration.requirements[0].quantity == 2
    assert configuration.booking_policy_revision == 0
    assert configuration.booking_policy.slot_step_minutes == 30
    first = await reader.list_resource_capabilities(
        scenario.organization_id,
        principal_id=scenario.principal_id,
        limit=2,
        after_id=None,
    )
    second = await reader.list_resource_capabilities(
        scenario.organization_id,
        principal_id=scenario.principal_id,
        limit=2,
        after_id=first[-1].capability_id,
    )
    assert len(first) == 2 and len(second) == 1
    assert len({item.capability_id for page in (first, second) for item in page}) == 3
    assert (
        await reader.read_offering_configuration(
            scenario.organization_id, uuid4(), principal_id=scenario.principal_id
        )
        is None
    )
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='catalog.read_configuration'",
        (scenario.principal_id, scenario.principal_id),
    )
    with pytest.raises(CapabilityRequired):
        await reader.read_offering_configuration(
            scenario.organization_id,
            scenario.offering_version_id,
            principal_id=scenario.principal_id,
        )
    with pytest.raises(CapabilityRequired):
        await reader.list_resource_capabilities(
            scenario.organization_id,
            principal_id=scenario.principal_id,
            limit=2,
            after_id=None,
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_offering_reader_keyset_handles_equal_display_names_without_duplicates(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    for _ in range(2):
        row = admin_conn.execute(
            """INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
            VALUES (%s, %s, 'Cardiology consultation') RETURNING id""",
            (scenario.organization_id, f"consultation-{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        admin_conn.execute(
            """INSERT INTO request_engine.offering_versions (
                organization_id, offering_id, version, duration_minutes
            ) VALUES (%s, %s, 1, 30)""",
            (scenario.organization_id, row[0]),
        )
    reader = PostgresOfferingCatalogReader(session_factory)
    first = await reader.search_offerings(
        SearchOfferingsQuery(
            scenario.organization_id,
            limit=2,
            include_page_probe=True,
        )
    )
    assert len(first) == 3  # probe exposes a real further row, not an exact-size guess
    second = await reader.search_offerings(
        SearchOfferingsQuery(
            scenario.organization_id,
            limit=2,
            include_page_probe=True,
            after_display_name=first[1].display_name,
            after_id=first[1].id,
        )
    )
    assert len(second) == 1 and second[0].id == first[2].id
