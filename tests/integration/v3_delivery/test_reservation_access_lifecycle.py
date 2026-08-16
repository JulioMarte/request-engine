from typing import Any, cast

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.delivery.adapters.db.reservation_access import (
    PostgresDeliveryPolicyReader,
    PostgresReservationAccessRepository,
)
from request_engine.modules.delivery.application.access import ReservationAccessService
from request_engine.modules.delivery.contracts.access import AccessStatus
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from ._fixture import DeliveryFixture, make_delivery_fixture, make_work_claim, source_from_db
from ._provider import RecordingProvider

PgConnection = Connection[Any]


def _service(
    session_factory: SessionFactory,
    provider: RecordingProvider,
) -> ReservationAccessService:
    return ReservationAccessService(
        PostgresDeliveryPolicyReader(session_factory),
        PostgresReservationAccessRepository(session_factory),
        {"meeting": provider},
    )


def _rows(
    conn: PgConnection,
    fixture: DeliveryFixture,
) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """
        SELECT reservation_revision, access_key, status
        FROM request_engine.reservation_access
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY reservation_revision, access_key
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    return [(cast(int, row[0]), cast(str, row[1]), cast(str, row[2])) for row in rows]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_app_materializes_provider_and_static_access(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"},
            {
                "key": "address",
                "kind": "physical_location",
                "public_data": {"line1": "Main 1"},
            },
        ],
    )
    provider = RecordingProvider()
    source = source_from_db(admin_conn, fixture)
    claim = make_work_claim(admin_conn, fixture)
    service = _service(delivery_session_factory, provider)

    ready = await service.reconcile_reservation_access(source, work_claim=claim)

    assert [access.access_key for access in ready] == ["video", "address"]
    assert all(access.status is AccessStatus.READY for access in ready)
    assert provider.created_resources == 1
    assert _rows(admin_conn, fixture) == [
        (1, "address", "ready"),
        (1, "video", "ready"),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_retry_recovers_pending_after_provider_failure(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[{"key": "video", "kind": "video_link", "provider": "meeting"}],
    )
    provider = RecordingProvider(provision_failures=1)
    source = source_from_db(admin_conn, fixture)
    claim = make_work_claim(admin_conn, fixture)
    service = _service(delivery_session_factory, provider)

    with pytest.raises(RuntimeError, match="provisioning unavailable"):
        await service.reconcile_reservation_access(source, work_claim=claim)

    assert _rows(admin_conn, fixture) == [(1, "video", "pending")]

    ready = await service.reconcile_reservation_access(source, work_claim=claim)

    assert ready[0].status is AccessStatus.READY
    assert provider.provision_calls == 2
    assert provider.created_resources == 1
    assert _rows(admin_conn, fixture) == [(1, "video", "ready")]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_worker_cannot_read_or_mutate_reservation_access_but_app_can(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[{"key": "video", "kind": "video_link", "provider": "meeting"}],
    )
    provider = RecordingProvider()
    source = source_from_db(admin_conn, fixture)
    claim = make_work_claim(admin_conn, fixture)
    service = _service(delivery_session_factory, provider)
    ready = await service.reconcile_reservation_access(source, work_claim=claim)
    access_id = ready[0].id

    with pytest.raises(DBAPIError):
        async with tenant_transaction(worker_session_factory, fixture.organization_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE request_engine.reservation_access
                    SET public_data = public_data
                    WHERE organization_id = :organization_id AND id = :access_id
                    """
                ),
                {
                    "organization_id": fixture.organization_id,
                    "access_id": access_id,
                },
            )

    with pytest.raises(DBAPIError):
        async with tenant_transaction(worker_session_factory, fixture.organization_id) as session:
            await session.execute(
                text(
                    """
                    SELECT id
                    FROM request_read.reservation_access_v1
                    WHERE organization_id = :organization_id
                    """
                ),
                {"organization_id": fixture.organization_id},
            )

    async with tenant_transaction(delivery_session_factory, fixture.organization_id) as session:
        result = await session.execute(
            text(
                """
                UPDATE request_engine.reservation_access
                SET public_data = public_data
                WHERE organization_id = :organization_id AND id = :access_id
                RETURNING id
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "access_id": access_id,
            },
        )
        assert result.scalar_one() == access_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_manual_policy_is_not_materialized(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {
                "key": "video",
                "kind": "video_link",
                "provider": "meeting",
                "provisioning": "manual",
            }
        ],
    )
    provider = RecordingProvider()
    service = _service(delivery_session_factory, provider)

    ready = await service.reconcile_reservation_access(
        source_from_db(admin_conn, fixture),
        work_claim=make_work_claim(admin_conn, fixture),
    )

    assert ready == ()
    assert provider.provision_calls == 0
    assert _rows(admin_conn, fixture) == []
