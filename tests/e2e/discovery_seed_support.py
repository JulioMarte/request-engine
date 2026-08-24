from __future__ import annotations

from datetime import UTC, datetime
from typing import LiteralString, cast
from uuid import UUID, uuid4

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def _uuid_row(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_classification(conn: PgConnection) -> tuple[UUID, str]:
    key = f"cardiology_e2e_{uuid4().hex}"
    classification_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_classifications (classification_key, canonical_name)
        VALUES (%s, 'Cardiology E2E') RETURNING id
        """,
        (key,),
    )
    return classification_id, key


def publish_sandbox(
    conn: PgConnection,
    sandbox: TenantSandbox,
    classification_id: UUID,
    *,
    latitude: float,
    longitude: float,
    resource_id: UUID | None = None,
    provider_visibility: str = "hidden",
) -> None:
    conn.execute(
        "UPDATE request_engine.locations SET latitude = %s, longitude = %s WHERE id = %s",
        (latitude, longitude, sandbox.location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_service_classifications (
            organization_id, offering_id, service_classification_id
        ) VALUES (%s, %s, %s)
        """,
        (sandbox.organization_id, sandbox.offering_id, classification_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.discovery_publications (
            organization_id, offering_id, location_id, resource_id,
            effective_during, provider_visibility
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2029-01-01T00:00:00+00', '2031-01-01T00:00:00+00', '[)'), %s
        )
        """,
        (
            sandbox.organization_id,
            sandbox.offering_id,
            sandbox.location_id,
            resource_id,
            provider_visibility,
        ),
    )


def search_body(classification_key: str) -> dict[str, object]:
    return {
        "service_classification_key": classification_key,
        "origin_latitude": "19.8000",
        "origin_longitude": "-70.7000",
        "radius_meters": 2_000,
        "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
        "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        "limit": 20,
    }
