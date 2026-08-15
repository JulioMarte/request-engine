from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)

PgConnection = Connection[Any]


async def _create_idempotency_subject(
    admin_conn: PgConnection,
) -> tuple[UUID, UUID, str]:
    suffix = uuid4().hex
    organization_row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Idempotency contract')
        RETURNING id
        """,
        (f"idempotency-contract-{suffix}",),
    ).fetchone()
    assert organization_row is not None
    organization_id = cast(UUID, organization_row[0])

    principal_row = admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    ).fetchone()
    assert principal_row is not None
    return organization_id, cast(UUID, principal_row[0]), suffix


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_idempotency_fingerprint_mismatch_has_semantic_error(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, suffix = await _create_idempotency_subject(admin_conn)

    key = f"same-key-{suffix}"
    async with tenant_transaction(session_factory, organization_id) as session:
        idempotency_id, replay = await acquire_idempotency(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            capability="requests.cancel",
            idempotency_key=key,
            fingerprint="fingerprint-a",
        )
        assert replay is None
        await complete_idempotency(session, idempotency_id, {"ok": True})

    with pytest.raises(IdempotencyConflict) as captured:
        async with tenant_transaction(session_factory, organization_id) as session:
            await acquire_idempotency(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability="requests.cancel",
                idempotency_key=key,
                fingerprint="fingerprint-b",
            )

    assert captured.value.capability == "requests.cancel"
    assert captured.value.idempotency_key == key


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r19_committed_effect_is_replayed_after_response_loss(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """Model COMMIT success followed by transport loss before the caller sees the result."""

    organization_id, principal_id, suffix = await _create_idempotency_subject(admin_conn)
    key = f"lost-response-{suffix}"
    effect_key = f"logical-effect-{suffix}"

    # First request commits both its logical effect and replay record. The test intentionally
    # discards the returned result, which is equivalent to losing the HTTP response after COMMIT.
    async with tenant_transaction(session_factory, organization_id) as session:
        idempotency_id, replay = await acquire_idempotency(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            capability="requests.cancel",
            idempotency_key=key,
            fingerprint="stable-fingerprint",
        )
        assert replay is None
        await session.execute(
            text(
                """
                INSERT INTO request_engine.outbox_messages (
                    organization_id,
                    event_type,
                    aggregate_kind,
                    aggregate_id,
                    payload,
                    next_attempt_at
                ) VALUES (
                    :organization_id,
                    'test.idempotent_effect.v1',
                    'IdempotencyProbe',
                    :aggregate_id,
                    CAST(:payload AS jsonb),
                    clock_timestamp()
                )
                """
            ),
            {
                "organization_id": organization_id,
                "aggregate_id": uuid4(),
                "payload": f'{{"effect_key":"{effect_key}"}}',
            },
        )
        await complete_idempotency(
            session,
            idempotency_id,
            {"effect_key": effect_key, "accepted": True},
        )

    # Client retries because it never observed the committed response.
    async with tenant_transaction(session_factory, organization_id) as session:
        replay_id, replay = await acquire_idempotency(
            session,
            organization_id=organization_id,
            principal_id=principal_id,
            capability="requests.cancel",
            idempotency_key=key,
            fingerprint="stable-fingerprint",
        )

    assert replay_id == idempotency_id
    assert replay == {"effect_key": effect_key, "accepted": True}
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'test.idempotent_effect.v1'
          AND payload ->> 'effect_key' = %s
        """,
        (organization_id, effect_key),
    ).fetchone() == (1,)
