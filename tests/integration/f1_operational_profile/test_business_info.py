from datetime import UTC, datetime, time
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.business_info_reader import PostgresBusinessInfoReader
from request_engine.modules.catalog.application.queries.get_business_info import get_business_info
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_business_info_exposes_typed_public_operational_truth_only(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    organization_id = cast(
        UUID,
        admin_conn.execute(
            """
            INSERT INTO request_engine.organizations (
                organization_key, display_name, legal_name,
                default_timezone, default_locale, default_currency
            ) VALUES (%s, 'Clinica Demo', 'Clinica Demo SRL',
                      'America/Santo_Domingo', 'es-DO', 'DOP')
            RETURNING id
            """,
            (f"clinic-{suffix}",),
        ).fetchone()[0],
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.organization_public_contact_endpoints (
            organization_id, channel, normalized_value, label, is_public
        ) VALUES
            (%s, 'whatsapp', '+18095550101', 'Citas', true),
            (%s, 'email', 'internal@example.test', 'Internal', false)
        """,
        (organization_id, organization_id),
    )
    location_id = cast(
        UUID,
        admin_conn.execute(
            """
            INSERT INTO request_engine.locations (
                organization_id, location_key, display_name, timezone,
                address_line1, locality, administrative_area, postal_code, country_code
            ) VALUES (%s, %s, 'Puerto Plata', 'America/Santo_Domingo',
                      'Av. Demo 123', 'Puerto Plata', 'Puerto Plata', '57000', 'DO')
            RETURNING id
            """,
            (organization_id, f"puerto-plata-{suffix}"),
        ).fetchone()[0],
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.location_public_contact_endpoints (
            organization_id, location_id, channel, normalized_value, label
        ) VALUES (%s, %s, 'phone', '+18095550202', 'Recepcion')
        """,
        (organization_id, location_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.location_hours_exceptions (
            organization_id, location_id, during, exception_kind, reason
        ) VALUES (
            %s, %s,
            tstzrange('2030-12-24T16:00:00+00'::timestamptz,
                      '2030-12-25T04:00:00+00'::timestamptz, '[)'),
            'unavailable', 'internal operational reason'
        )
        """,
        (organization_id, location_id),
    )

    info = await get_business_info(PostgresBusinessInfoReader(session_factory), organization_id)

    assert info.display_name == "Clinica Demo"
    assert info.legal_name == "Clinica Demo SRL"
    assert info.default_timezone == "America/Santo_Domingo"
    assert info.default_locale == "es-DO"
    assert info.default_currency == "DOP"
    assert [(item.channel, item.value) for item in info.contacts] == [
        ("whatsapp", "+18095550101")
    ]

    assert len(info.locations) == 1
    location = info.locations[0]
    assert location.id == location_id
    assert location.address_line1 == "Av. Demo 123"
    assert location.locality == "Puerto Plata"
    assert location.country_code == "DO"
    assert [(item.channel, item.value) for item in location.contacts] == [
        ("phone", "+18095550202")
    ]
    assert len(location.operational_hours) == 1
    window = location.operational_hours[0]
    assert window.weekday == 0
    assert window.local_start == time(8, 0)
    assert window.local_end == time(17, 0)
    assert len(location.hours_exceptions) == 1
    exception = location.hours_exceptions[0]
    assert exception.kind == "unavailable"
    assert exception.start_at == datetime(2030, 12, 24, 16, 0, tzinfo=UTC)
    assert exception.end_at == datetime(2030, 12, 25, 4, 0, tzinfo=UTC)
