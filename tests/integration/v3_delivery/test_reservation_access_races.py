import asyncio
from typing import Any, cast

import pytest
from psycopg import Connection

from request_engine.modules.delivery.adapters.db.reservation_access import (
    PostgresDeliveryPolicyReader,
    PostgresReservationAccessRepository,
)
from request_engine.modules.delivery.application.access import ReservationAccessService
from request_engine.modules.delivery.contracts.access import (
    AccessStatus,
    ProvisionAccessRequest,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.worker.runtime import LeaseLostWorkError

from ._fixture import (
    DeliveryFixture,
    bump_reservation_revision,
    cancel_reservation,
    make_delivery_fixture,
    make_work_claim,
    replace_work_claim,
    source_from_db,
)
from ._provider import RacingProvider, RecordingProvider

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
) -> list[tuple[int, str, str, str]]:
    rows = conn.execute(
        """
        SELECT reservation_revision, access_key, status, materialization_key
        FROM request_engine.reservation_access
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY reservation_revision, access_key
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    return [
        (
            cast(int, row[0]),
            cast(str, row[1]),
            cast(str, row[2]),
            cast(str, row[3]),
        )
        for row in rows
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_reconcile_creates_one_semantic_provider_resource(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RecordingProvider()
    service = _service(delivery_session_factory, provider)
    source = source_from_db(admin_conn, fixture)
    claim = make_work_claim(admin_conn, fixture)

    results = await asyncio.gather(
        service.reconcile_reservation_access(source, work_claim=claim),
        service.reconcile_reservation_access(source, work_claim=claim),
        return_exceptions=True,
    )

    assert all(not isinstance(result, BaseException) for result in results)
    assert provider.created_resources == 1
    assert _rows(admin_conn, fixture)[0][2] == "ready"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_lost_outbox_lease_cannot_publish_but_replay_reuses_provider_evidence(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RacingProvider()
    service = _service(delivery_session_factory, provider)
    source = source_from_db(admin_conn, fixture)
    first_claim = make_work_claim(admin_conn, fixture)

    task = asyncio.create_task(
        service.reconcile_reservation_access(source, work_claim=first_claim)
    )
    await asyncio.wait_for(provider.provision_started.wait(), timeout=10)
    replacement = replace_work_claim(admin_conn, first_claim)
    provider.release_provision.set()

    with pytest.raises(LeaseLostWorkError):
        await task

    rows = _rows(admin_conn, fixture)
    assert rows[0][2] == "pending"
    assert provider.created_resources == 1
    provision_calls_after_stale = provider.provision_calls

    ready = await service.reconcile_reservation_access(source, work_claim=replacement)

    assert ready[0].status is AccessStatus.READY
    assert provider.provision_calls == provision_calls_after_stale
    assert provider.created_resources == 1
    assert _rows(admin_conn, fixture)[0][2] == "ready"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reschedule_revokes_old_revision_before_new_revision_is_ready(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RecordingProvider()
    service = _service(delivery_session_factory, provider)

    source_v1 = source_from_db(admin_conn, fixture)
    claim_v1 = make_work_claim(admin_conn, fixture)
    ready_v1 = await service.reconcile_reservation_access(source_v1, work_claim=claim_v1)
    old_key = ready_v1[0].materialization_key

    bump_reservation_revision(admin_conn, fixture)
    source_v2 = source_from_db(admin_conn, fixture)
    claim_v2 = make_work_claim(
        admin_conn, fixture, event_type="reservation.rescheduled.v1"
    )
    ready_v2 = await service.reconcile_reservation_access(source_v2, work_claim=claim_v2)

    rows = _rows(admin_conn, fixture)
    assert [(row[0], row[2]) for row in rows] == [(1, "revoked"), (2, "ready")]
    assert old_key in provider.revoked_keys
    assert ready_v2[0].materialization_key != old_key
    assert provider.created_resources == 2


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_cancel_racing_provider_materialization_never_publishes_ready_access(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RacingProvider()
    service = _service(delivery_session_factory, provider)
    source = source_from_db(admin_conn, fixture)
    created_claim = make_work_claim(admin_conn, fixture)

    task = asyncio.create_task(
        service.reconcile_reservation_access(source, work_claim=created_claim)
    )
    await asyncio.wait_for(provider.provision_started.wait(), timeout=10)
    cancel_reservation(admin_conn, fixture)
    provider.release_provision.set()

    result = await task
    assert result == ()

    rows = _rows(admin_conn, fixture)
    assert rows[0][2] == "revoked"
    assert rows[0][3] in provider.revoked_keys
    assert all(row[2] != "ready" for row in rows)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_stale_reservation_revision_cannot_revoke_current_ready_access(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RecordingProvider()
    service = _service(delivery_session_factory, provider)

    stale_source = source_from_db(admin_conn, fixture)
    bump_reservation_revision(admin_conn, fixture)
    current_source = source_from_db(admin_conn, fixture)
    current_claim = make_work_claim(
        admin_conn, fixture, event_type="reservation.rescheduled.v1"
    )
    ready = await service.reconcile_reservation_access(
        current_source, work_claim=current_claim
    )
    current_key = ready[0].materialization_key

    stale_claim = make_work_claim(admin_conn, fixture)
    stale_result = await service.reconcile_reservation_access(
        stale_source, work_claim=stale_claim
    )

    assert stale_result == ()
    assert _rows(admin_conn, fixture) == [(2, "video", "ready", current_key)]
    assert current_key not in provider.revoked_keys


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_cancel_recovers_provider_success_that_crashed_before_db_evidence(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RecordingProvider()
    repository = PostgresReservationAccessRepository(delivery_session_factory)
    policy_reader = PostgresDeliveryPolicyReader(delivery_session_factory)
    source = source_from_db(admin_conn, fixture)
    created_claim = make_work_claim(admin_conn, fixture)
    policy = (
        await policy_reader.get_access_policies(
            fixture.organization_id, fixture.offering_version_id
        )
    )[0]

    pending = await repository.ensure_pending(source, policy, created_claim)
    assert pending is not None
    assert pending.provisioned_at is None
    materialized = await provider.provision(
        ProvisionAccessRequest(
            source=source,
            access_key=policy.access_key,
            kind=policy.kind,
            public_data=policy.public_data,
            materialization_key=pending.materialization_key,
        )
    )
    assert materialized.external_ref is not None

    cancel_reservation(admin_conn, fixture)
    cancel_claim = make_work_claim(
        admin_conn, fixture, event_type="reservation.cancelled.v1"
    )
    service = _service(delivery_session_factory, provider)
    revoked = await service.revoke_reservation_access(
        fixture.organization_id,
        fixture.reservation_id,
        work_claim=cancel_claim,
    )

    assert revoked[0].status is AccessStatus.REVOKED
    assert provider.lookup_calls == 1
    assert pending.materialization_key in provider.revoked_keys
    assert _rows(admin_conn, fixture)[0][2] == "revoked"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_provider_revoke_failure_leaves_local_access_retryable(
    admin_conn: PgConnection,
    delivery_session_factory: SessionFactory,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {"key": "video", "kind": "video_link", "provider": "meeting"}
        ],
    )
    provider = RecordingProvider(revoke_failures=1)
    service = _service(delivery_session_factory, provider)
    source = source_from_db(admin_conn, fixture)
    await service.reconcile_reservation_access(
        source, work_claim=make_work_claim(admin_conn, fixture)
    )
    cancel_reservation(admin_conn, fixture)
    cancel_claim = make_work_claim(
        admin_conn, fixture, event_type="reservation.cancelled.v1"
    )

    with pytest.raises(RuntimeError, match="revocation unavailable"):
        await service.revoke_reservation_access(
            fixture.organization_id,
            fixture.reservation_id,
            work_claim=cancel_claim,
        )
    assert _rows(admin_conn, fixture)[0][2] == "ready"

    revoked = await service.revoke_reservation_access(
        fixture.organization_id,
        fixture.reservation_id,
        work_claim=cancel_claim,
    )
    assert revoked[0].status is AccessStatus.REVOKED
    assert _rows(admin_conn, fixture)[0][2] == "revoked"
