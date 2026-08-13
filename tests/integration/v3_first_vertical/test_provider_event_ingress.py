from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.providers.events import (
    PostgresProviderEventIngress,
    ProviderEventPayloadMismatch,
    VerifiedProviderConnection,
)

PgConnection = Connection[Any]


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"provider-events-{suffix}", f"Provider Events {suffix}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_provider_event_ingress_is_deduped_and_schedules_processing_once(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    connection = VerifiedProviderConnection(
        organization_id=organization_id,
        provider_key="test-provider",
        connection_key="primary",
    )
    ingress = PostgresProviderEventIngress(session_factory)
    external_event_id = f"evt-{uuid4().hex}"
    payload = {"type": "message.delivered", "message_id": uuid4().hex}

    first = await ingress.record(
        connection,
        provider_event_id=external_event_id,
        payload=payload,
    )
    second = await ingress.record(
        connection,
        provider_event_id=external_event_id,
        payload=payload,
    )

    assert first.replay is False
    assert second.replay is True
    assert second.id == first.id

    rows = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.provider_events
        WHERE organization_id = %s
          AND provider_key = 'test-provider'
          AND connection_key = 'primary'
          AND provider_event_id = %s
        """,
        (organization_id, external_event_id),
    ).fetchone()
    assert rows == (1,)

    scheduled = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'provider_events'
          AND action_type = 'process_event'
          AND subject_kind = 'ProviderEvent'
          AND subject_id = %s
        """,
        (organization_id, first.id),
    ).fetchone()
    assert scheduled == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_provider_event_id_reuse_with_changed_payload_is_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    connection = VerifiedProviderConnection(
        organization_id=_organization(admin_conn),
        provider_key="test-provider",
        connection_key="primary",
    )
    ingress = PostgresProviderEventIngress(session_factory)
    external_event_id = f"evt-{uuid4().hex}"

    await ingress.record(
        connection,
        provider_event_id=external_event_id,
        payload={"status": "accepted"},
    )

    with pytest.raises(ProviderEventPayloadMismatch):
        await ingress.record(
            connection,
            provider_event_id=external_event_id,
            payload={"status": "delivered"},
        )
