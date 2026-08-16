import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

from request_engine.modules.delivery.contracts.access import (
    DeliveryWorkClaim,
    ReservationAccessSource,
)

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class DeliveryFixture:
    organization_id: UUID
    subject_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    reservation_id: UUID
    start_at: datetime
    end_at: datetime


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _future_start() -> datetime:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    aligned = now + timedelta(minutes=(-now.minute) % 15)
    return aligned + timedelta(days=3)


def make_delivery_fixture(
    conn: PgConnection,
    *,
    access_policies: list[dict[str, object]],
    reservation_status: str = "confirmed",
    reservation_revision: int = 1,
) -> DeliveryFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"delivery-{suffix}", f"Delivery {suffix}"),
    )
    subject_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (organization_id, offering_key, display_name)
        VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable,
            booking_policy, delivery_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            offering_id,
            json.dumps({"slot_step_minutes": 15}),
            json.dumps({"access": access_policies}),
        ),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Provider')
        RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Provider', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"provider-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    start_at = _future_start()
    end_at = start_at + timedelta(minutes=30)
    with conn.transaction():
        reservation_id = _uuid_row(
            conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, during,
                status, revision, booking_policy_snapshot
            ) VALUES (%s, %s, %s, tstzrange(%s, %s, '[)'), %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                organization_id,
                offering_version_id,
                subject_id,
                start_at,
                end_at,
                reservation_status,
                reservation_revision,
                json.dumps({"slot_step_minutes": 15}),
            ),
        )
        conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, reservation_id,
                during, quantity
            ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), 1)
            """,
            (
                organization_id,
                resource_id,
                requirement_id,
                reservation_id,
                start_at,
                end_at,
            ),
        )
    return DeliveryFixture(
        organization_id=organization_id,
        subject_id=subject_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        reservation_id=reservation_id,
        start_at=start_at,
        end_at=end_at,
    )


def source_from_db(
    conn: PgConnection,
    fixture: DeliveryFixture,
) -> ReservationAccessSource:
    row = conn.execute(
        """
        SELECT offering_version_id, subject_party_id, location_id, status, revision,
               lower(during), upper(during)
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert row is not None
    return ReservationAccessSource(
        organization_id=fixture.organization_id,
        reservation_id=fixture.reservation_id,
        offering_version_id=cast(UUID, row[0]),
        subject_party_id=cast(UUID, row[1]),
        location_id=cast(UUID | None, row[2]),
        status=cast(str, row[3]),
        revision=cast(int, row[4]),
        start_at=cast(datetime, row[5]),
        end_at=cast(datetime, row[6]),
    )


def make_work_claim(
    conn: PgConnection,
    fixture: DeliveryFixture,
    *,
    event_type: str = "reservation.created.v1",
) -> DeliveryWorkClaim:
    token = uuid4()
    message_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, schema_version, aggregate_kind,
            aggregate_id, payload, status, claim_token, lease_until, attempt_count
        ) VALUES (
            %s, %s, 1, 'Reservation', %s, %s::jsonb,
            'leased', %s, clock_timestamp() + interval '5 minutes', 1
        )
        RETURNING id
        """,
        (
            fixture.organization_id,
            event_type,
            fixture.reservation_id,
            json.dumps({"reservation_id": str(fixture.reservation_id)}),
            token,
        ),
    )
    return DeliveryWorkClaim(fixture.organization_id, message_id, token)


def replace_work_claim(
    conn: PgConnection,
    claim: DeliveryWorkClaim,
) -> DeliveryWorkClaim:
    token = uuid4()
    conn.execute(
        """
        UPDATE request_engine.outbox_messages
        SET claim_token = %s,
            lease_until = clock_timestamp() + interval '5 minutes',
            status = 'leased',
            attempt_count = attempt_count + 1
        WHERE organization_id = %s AND id = %s
        """,
        (token, claim.organization_id, claim.message_id),
    )
    return DeliveryWorkClaim(claim.organization_id, claim.message_id, token)


def cancel_reservation(
    conn: PgConnection,
    fixture: DeliveryFixture,
) -> None:
    with conn.transaction():
        conn.execute(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp()
            WHERE organization_id = %s
              AND reservation_id = %s
              AND status = 'active'
            """,
            (fixture.organization_id, fixture.reservation_id),
        )
        conn.execute(
            """
            UPDATE request_engine.reservations
            SET status = 'cancelled',
                cancelled_at = clock_timestamp(),
                revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, fixture.reservation_id),
        )


def bump_reservation_revision(
    conn: PgConnection,
    fixture: DeliveryFixture,
) -> None:
    conn.execute(
        """
        UPDATE request_engine.reservations
        SET revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    )
