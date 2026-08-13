from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_idempotency_fingerprint_mismatch_has_semantic_error(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
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
    principal_id = cast(UUID, principal_row[0])

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

    async with tenant_transaction(session_factory, organization_id) as session:
        with pytest.raises(IdempotencyConflict) as captured:
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
