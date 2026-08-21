import asyncio
from datetime import UTC, date, datetime, time
from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
    set_resource_location_availability,
)
from request_engine.modules.booking.application.operational_errors import (
    ResourceAvailabilityRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _resource_revision(conn: PgConnection, fixture: F1ContextualScenario) -> int:
    row = conn.execute(
        """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.resource_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_overlapping_context_terms_serialize_and_one_is_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    admin_conn.execute(
        """
        UPDATE request_engine.booking_context_terms
           SET active = false
         WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.context_terms_id),
    )

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def insert_terms(amount: int, hold_open: bool) -> str:
        try:
            async with tenant_transaction(
                session_factory,
                fixture.organization_id,
            ) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.booking_context_terms (
                            organization_id,
                            resource_location_assignment_id,
                            offering_version_id,
                            effective_during,
                            amount,
                            currency
                        ) VALUES (
                            :organization_id,
                            :assignment_id,
                            :offering_version_id,
                            tstzrange(
                                '2027-01-01T00:00:00+00'::timestamptz,
                                '2028-01-01T00:00:00+00'::timestamptz,
                                '[)'
                            ),
                            :amount,
                            'DOP'
                        )
                        """
                    ),
                    {
                        "organization_id": fixture.organization_id,
                        "assignment_id": fixture.assignment_id,
                        "offering_version_id": fixture.offering_version_id,
                        "amount": amount,
                    },
                )
                if hold_open:
                    first_entered.set()
                    await release_first.wait()
            return "ok"
        except IntegrityError:
            return "overlap"

    first = asyncio.create_task(insert_terms(4100, True))
    await asyncio.wait_for(first_entered.wait(), timeout=5)
    second = asyncio.create_task(insert_terms(4200, False))
    await asyncio.sleep(0.1)
    assert not second.done()
    release_first.set()

    outcomes = await asyncio.gather(first, second)
    assert outcomes.count("ok") == 1
    assert outcomes.count("overlap") == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_overlapping_assignments_serialize_and_one_is_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    admin_conn.execute(
        """
        UPDATE request_engine.resource_location_assignments
           SET effective_during = tstzrange(
               lower(effective_during),
               '2027-01-01T00:00:00+00'::timestamptz,
               '[)'
           )
         WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.assignment_id),
    )

    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def insert_assignment(hold_open: bool) -> str:
        try:
            async with tenant_transaction(
                session_factory,
                fixture.organization_id,
            ) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.resource_location_assignments (
                            organization_id,
                            resource_id,
                            location_id,
                            effective_during
                        ) VALUES (
                            :organization_id,
                            :resource_id,
                            :location_id,
                            tstzrange(
                                '2028-01-01T00:00:00+00'::timestamptz,
                                NULL,
                                '[)'
                            )
                        )
                        """
                    ),
                    {
                        "organization_id": fixture.organization_id,
                        "resource_id": fixture.resource_id,
                        "location_id": fixture.location_id,
                    },
                )
                if hold_open:
                    first_entered.set()
                    await release_first.wait()
            return "ok"
        except IntegrityError:
            return "overlap"

    first = asyncio.create_task(insert_assignment(True))
    await asyncio.wait_for(first_entered.wait(), timeout=5)
    second = asyncio.create_task(insert_assignment(False))
    await asyncio.sleep(0.1)
    assert not second.done()
    release_first.set()

    outcomes = await asyncio.gather(first, second)
    assert outcomes.count("ok") == 1
    assert outcomes.count("overlap") == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_schedule_replacements_use_revision_as_stale_intent_guard(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    initial_revision = _resource_revision(admin_conn, fixture)
    handler = PostgresContextualSupplyLifecycleCommands(session_factory)

    async def replace(start_hour: int) -> object:
        return await set_resource_location_availability(
            handler,
            SetResourceLocationAvailabilityCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                authority_party_id=fixture.authority_party_id,
                assignment_id=fixture.assignment_id,
                windows=(
                    ResourceLocationAvailabilityWindow(
                        weekday=0,
                        local_start=time(start_hour),
                        local_end=time(17),
                        valid_from=date(2026, 1, 1),
                    ),
                ),
                expected_resource_availability_revision=initial_revision,
                idempotency_key=f"schedule-race-{start_hour}-{uuid4().hex}",
            ),
        )

    outcomes = await asyncio.gather(
        replace(8),
        replace(9),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if not isinstance(item, BaseException)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ResourceAvailabilityRevisionConflict)

    rows = admin_conn.execute(
        """
        SELECT local_start, local_end
        FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
        """,
        (fixture.organization_id, fixture.assignment_id),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == time(17)
    assert rows[0][0] in {time(8), time(9)}
