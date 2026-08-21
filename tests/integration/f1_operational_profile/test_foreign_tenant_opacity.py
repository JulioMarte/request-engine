from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.catalog.adapters.db.location_creation_commands import (
    PostgresLocationCreationCommands,
)
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.application.commands.create_location import (
    CreateLocationCommand,
    create_location,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    SearchOfferingsQuery,
    search_offerings,
)
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.application.commands.set_organization_public_contacts import (
    OrganizationPublicContactInput,
    SetOrganizationPublicContactsCommand,
    set_organization_public_contacts,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.operational_authority import (
    OperationalAuthorityRequired,
)

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_and_random_authority_party_ids_have_same_observable_rejection(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    local = create_contextual_cardiology_scenario(admin_conn)
    foreign = create_contextual_cardiology_scenario(admin_conn)
    random_party_id = uuid4()

    create_handler = PostgresLocationCreationCommands(session_factory)
    contact_handler = PostgresOperationalProfileCommands(session_factory)

    for authority_party_id in (foreign.authority_party_id, random_party_id):
        with pytest.raises(OperationalAuthorityRequired):
            await create_location(
                create_handler,
                CreateLocationCommand(
                    organization_id=local.organization_id,
                    principal_id=local.principal_id,
                    authority_party_id=authority_party_id,
                    location_key=f"opaque-{uuid4().hex}",
                    display_name="Opaque target",
                    timezone="America/Santo_Domingo",
                    idempotency_key=f"opaque-create-{uuid4().hex}",
                ),
            )

        with pytest.raises(OperationalAuthorityRequired):
            await set_organization_public_contacts(
                contact_handler,
                SetOrganizationPublicContactsCommand(
                    organization_id=local.organization_id,
                    principal_id=local.principal_id,
                    authority_party_id=authority_party_id,
                    contacts=(
                        OrganizationPublicContactInput("phone", "+18095550001"),
                    ),
                    idempotency_key=f"opaque-contact-{uuid4().hex}",
                ),
            )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_and_random_location_ids_are_equally_absent_from_discovery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    local = create_contextual_cardiology_scenario(admin_conn)
    foreign = create_contextual_cardiology_scenario(admin_conn)
    random_location_id = uuid4()
    catalog = PostgresOfferingCatalogReader(session_factory)
    availability = PostgresAppointmentAvailabilityReader(session_factory)

    for location_id in (foreign.location_id, random_location_id):
        offerings = await search_offerings(
            catalog,
            SearchOfferingsQuery(
                organization_id=local.organization_id,
                search_text="cardiology",
                location_id=location_id,
                effective_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            ),
        )
        assert offerings == ()

        slots = await find_appointment_slots(
            availability,
            FindAppointmentSlotsQuery(
                organization_id=local.organization_id,
                offering_version_id=local.offering_version_id,
                location_id=location_id,
                window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
                window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
                limit=10,
            ),
        )
        assert slots == ()
