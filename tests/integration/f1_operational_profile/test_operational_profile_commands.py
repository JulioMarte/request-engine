from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.business_info_reader import (
    PostgresBusinessInfoReader,
)
from request_engine.modules.catalog.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.catalog.application.commands.configure_offering_version_booking_terms import (  # noqa: E501
    ConfigureOfferingVersionBookingTermsCommand,
    configure_offering_version_booking_terms,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    SetLocationHoursExceptionCommand,
    set_location_hours_exception,
)
from request_engine.modules.catalog.application.commands.set_location_public_contacts import (
    LocationPublicContactInput,
    SetLocationPublicContactsCommand,
    set_location_public_contacts,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    UpdateLocationOperationalInfoCommand,
    update_location_operational_info,
)
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    LocationOperationalRevisionConflict,
)
from request_engine.modules.catalog.application.queries.get_business_info import get_business_info
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _location_revision(conn: PgConnection, scenario: F1ContextualScenario) -> int:
    row = conn.execute(
        """
        SELECT operational_revision
        FROM request_engine.locations
        WHERE organization_id = %s AND id = %s
        """,
        (scenario.organization_id, scenario.location_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _new_offering_version_without_terms(conn: PgConnection, scenario: F1ContextualScenario) -> UUID:
    offering = conn.execute(
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Dermatology consultation')
        RETURNING id
        """,
        (scenario.organization_id, f"dermatology-{uuid4().hex}"),
    ).fetchone()
    assert offering is not None
    version = conn.execute(
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true)
        RETURNING id
        """,
        (scenario.organization_id, cast(UUID, offering[0])),
    ).fetchone()
    assert version is not None
    return cast(UUID, version[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_location_operational_info_updates_address_and_material_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresOperationalProfileCommands(session_factory)
    initial_revision = _location_revision(admin_conn, scenario)

    state = await update_location_operational_info(
        handler,
        UpdateLocationOperationalInfoCommand(
            organization_id=scenario.organization_id,
            principal_id=scenario.principal_id,
            authority_party_id=scenario.authority_party_id,
            location_id=scenario.location_id,
            timezone="America/New_York",
            active=True,
            expected_operational_revision=initial_revision,
            idempotency_key=f"location-info-{uuid4().hex}",
            address_line1="123 Main Street",
            locality="Puerto Plata",
            country_code="DO",
            latitude=Decimal("19.7934"),
            longitude=Decimal("-70.6884"),
            geocoding_source="test-fixture",
            geocoded_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        ),
    )

    assert state.timezone == "America/New_York"
    assert state.address_line1 == "123 Main Street"
    assert state.country_code == "DO"
    assert state.operational_revision == initial_revision + 1

    with pytest.raises(LocationOperationalRevisionConflict):
        await update_location_operational_info(
            handler,
            UpdateLocationOperationalInfoCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                location_id=scenario.location_id,
                timezone="America/Santo_Domingo",
                active=True,
                expected_operational_revision=initial_revision,
                idempotency_key=f"location-info-stale-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_public_contacts_are_visible_without_invalidating_booking_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresOperationalProfileCommands(session_factory)
    before_revision = _location_revision(admin_conn, scenario)
    command = SetLocationPublicContactsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        location_id=scenario.location_id,
        contacts=(
            LocationPublicContactInput("phone", "+18095550123", "Appointments"),
            LocationPublicContactInput("email", "appointments@example.test", None),
        ),
        idempotency_key=f"contacts-{uuid4().hex}",
    )

    state = await set_location_public_contacts(handler, command)
    replay = await set_location_public_contacts(handler, command)
    assert replay == state
    assert _location_revision(admin_conn, scenario) == before_revision

    info = await get_business_info(
        PostgresBusinessInfoReader(session_factory), scenario.organization_id
    )
    location = next(item for item in info.locations if item.id == scenario.location_id)
    assert {(item.channel, item.value) for item in location.contacts} == {
        ("phone", "+18095550123"),
        ("email", "appointments@example.test"),
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_location_hours_exception_is_revisioned_idempotent_and_overlap_safe(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresOperationalProfileCommands(session_factory)
    initial_revision = _location_revision(admin_conn, scenario)
    command = SetLocationHoursExceptionCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        location_id=scenario.location_id,
        start_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
        exception_kind="unavailable",
        reason="temporary closure",
        expected_operational_revision=initial_revision,
        idempotency_key=f"location-exception-{uuid4().hex}",
    )

    state = await set_location_hours_exception(handler, command)
    replay = await set_location_hours_exception(handler, command)
    assert replay == state
    assert state.operational_revision > initial_revision

    with pytest.raises(CatalogConfigurationConflict):
        await set_location_hours_exception(
            handler,
            SetLocationHoursExceptionCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                location_id=scenario.location_id,
                start_at=datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
                end_at=datetime(2026, 8, 17, 14, 30, tzinfo=UTC),
                exception_kind="unavailable",
                reason="overlap",
                expected_operational_revision=state.operational_revision,
                idempotency_key=f"location-exception-overlap-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_offering_version_base_terms_are_write_once_and_idempotent(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    offering_version_id = _new_offering_version_without_terms(admin_conn, scenario)
    handler = PostgresOperationalProfileCommands(session_factory)
    command = ConfigureOfferingVersionBookingTermsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        offering_version_id=offering_version_id,
        amount=Decimal("2750"),
        currency="DOP",
        idempotency_key=f"base-terms-{uuid4().hex}",
    )

    state = await configure_offering_version_booking_terms(handler, command)
    replay = await configure_offering_version_booking_terms(handler, command)
    assert replay == state
    assert state.amount == Decimal("2750")

    with pytest.raises(CatalogConfigurationConflict):
        await configure_offering_version_booking_terms(
            handler,
            ConfigureOfferingVersionBookingTermsCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                offering_version_id=offering_version_id,
                amount=Decimal("3000"),
                currency="DOP",
                idempotency_key=f"base-terms-second-{uuid4().hex}",
            ),
        )
