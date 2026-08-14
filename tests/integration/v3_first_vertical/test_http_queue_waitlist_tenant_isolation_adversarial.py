from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient, Response
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]

_TENANT_CAPABILITIES = frozenset(
    {
        "queue.list",
        "queue.join",
        "queue.status",
        "queue.leave",
        "queue.subject_override",
        "waitlist.join",
        "waitlist.read",
        "waitlist.leave",
        "waitlist.subject_override",
    }
)


@dataclass(frozen=True, slots=True)
class QueueWaitlistFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    queue_id: UUID
    offering_id: UUID


class BearerResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise AuthenticationRequired
        actor = self._actors.get(authorization.removeprefix("Bearer "))
        if actor is None:
            raise AuthenticationRequired
        return actor


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> QueueWaitlistFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"queue-isolation-{label}-{suffix}", f"Queue Isolation {label}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"queue-agent-{label}-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Patient {label}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"walkin-{label}-{suffix}", f"Walk-in {label}"),
    )
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name, offering_id
        ) VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"queue-{label}-{suffix}", f"Queue {label}", offering_id),
    )
    return QueueWaitlistFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        queue_id=queue_id,
        offering_id=offering_id,
    )


def _actor(fixture: QueueWaitlistFixture) -> ActorContext:
    return ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_TENANT_CAPABILITIES,
    )


def _client(
    session_factory: SessionFactory,
    tenant_a: QueueWaitlistFixture,
    tenant_b: QueueWaitlistFixture,
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(
            {
                "tenant-a": _actor(tenant_a),
                "tenant-b": _actor(tenant_b),
            }
        ),
        appointment_option_signing_key=b"x" * 64,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _error_shape(response: Response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, cast(str, error["code"]), cast(str, error["resolution"])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_queue_ids_behave_like_nonexistent_ids_and_cannot_be_mutated(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a")
    tenant_b = _fixture(admin_conn, "b")
    headers_a = {"Authorization": "Bearer tenant-a"}
    headers_b = {"Authorization": "Bearer tenant-b"}

    async with _client(session_factory, tenant_a, tenant_b) as client:
        joined_b = await client.post(
            f"/v1/queues/{tenant_b.queue_id}/join",
            json={"subject_party_id": str(tenant_b.subject_party_id)},
            headers={**headers_b, "Idempotency-Key": f"join-b-{uuid4().hex}"},
        )
        assert joined_b.status_code == 201
        entry_b_id = UUID(joined_b.json()["id"])
        entry_b_revision = cast(int, joined_b.json()["revision"])

        foreign_status = await client.get(
            f"/v1/queues/{tenant_b.queue_id}/status",
            params={"subject_party_id": str(tenant_b.subject_party_id)},
            headers=headers_a,
        )
        nonexistent_status = await client.get(
            f"/v1/queues/{uuid4()}/status",
            params={"subject_party_id": str(uuid4())},
            headers=headers_a,
        )
        assert _error_shape(foreign_status) == _error_shape(nonexistent_status)
        assert foreign_status.status_code == 404

        foreign_leave = await client.post(
            f"/v1/queues/{tenant_b.queue_id}/entries/{entry_b_id}/leave",
            json={"expected_revision": entry_b_revision, "reason": "cross-tenant attack"},
            headers={**headers_a, "Idempotency-Key": f"leave-foreign-{uuid4().hex}"},
        )
        nonexistent_leave = await client.post(
            f"/v1/queues/{uuid4()}/entries/{uuid4()}/leave",
            json={"expected_revision": entry_b_revision, "reason": "nonexistent control"},
            headers={**headers_a, "Idempotency-Key": f"leave-missing-{uuid4().hex}"},
        )
        assert _error_shape(foreign_leave) == _error_shape(nonexistent_leave)
        assert foreign_leave.status_code == 404

        foreign_queue_join = await client.post(
            f"/v1/queues/{tenant_b.queue_id}/join",
            json={"subject_party_id": str(tenant_a.subject_party_id)},
            headers={**headers_a, "Idempotency-Key": f"foreign-queue-{uuid4().hex}"},
        )
        foreign_party_join = await client.post(
            f"/v1/queues/{tenant_a.queue_id}/join",
            json={"subject_party_id": str(tenant_b.subject_party_id)},
            headers={**headers_a, "Idempotency-Key": f"foreign-party-{uuid4().hex}"},
        )
        assert 400 <= foreign_queue_join.status_code < 500
        assert 400 <= foreign_party_join.status_code < 500

        owner_status = await client.get(
            f"/v1/queues/{tenant_b.queue_id}/status",
            params={"subject_party_id": str(tenant_b.subject_party_id)},
            headers=headers_b,
        )
        assert owner_status.status_code == 200
        assert owner_status.json()["entry"]["id"] == str(entry_b_id)
        assert owner_status.json()["entry"]["revision"] == entry_b_revision

    foreign_rows = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.queue_entries
        WHERE organization_id = %s
          AND (
              service_queue_id = %s
              OR subject_party_id = %s
          )
        """,
        (tenant_a.organization_id, tenant_b.queue_id, tenant_b.subject_party_id),
    ).fetchone()
    assert foreign_rows == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_waitlist_ids_behave_like_nonexistent_ids_and_cannot_be_mutated(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a-waitlist")
    tenant_b = _fixture(admin_conn, "b-waitlist")
    headers_a = {"Authorization": "Bearer tenant-a"}
    headers_b = {"Authorization": "Bearer tenant-b"}

    async with _client(session_factory, tenant_a, tenant_b) as client:
        joined_b = await client.post(
            "/v1/waitlist",
            json={
                "offering_id": str(tenant_b.offering_id),
                "subject_party_id": str(tenant_b.subject_party_id),
            },
            headers={**headers_b, "Idempotency-Key": f"waitlist-b-{uuid4().hex}"},
        )
        assert joined_b.status_code == 201
        entry_b_id = UUID(joined_b.json()["id"])
        entry_b_revision = cast(int, joined_b.json()["revision"])

        foreign_read = await client.get(f"/v1/waitlist/{entry_b_id}", headers=headers_a)
        nonexistent_read = await client.get(f"/v1/waitlist/{uuid4()}", headers=headers_a)
        assert _error_shape(foreign_read) == _error_shape(nonexistent_read)
        assert _error_shape(foreign_read) == (
            404,
            "waitlist_entry_not_found",
            "refresh_and_retry",
        )

        foreign_leave = await client.post(
            f"/v1/waitlist/{entry_b_id}/leave",
            json={"expected_revision": entry_b_revision, "reason": "cross-tenant attack"},
            headers={**headers_a, "Idempotency-Key": f"waitlist-leave-{uuid4().hex}"},
        )
        nonexistent_leave = await client.post(
            f"/v1/waitlist/{uuid4()}/leave",
            json={"expected_revision": entry_b_revision, "reason": "nonexistent control"},
            headers={**headers_a, "Idempotency-Key": f"waitlist-missing-{uuid4().hex}"},
        )
        assert _error_shape(foreign_leave) == _error_shape(nonexistent_leave)
        assert foreign_leave.status_code == 404

        foreign_offering_join = await client.post(
            "/v1/waitlist",
            json={
                "offering_id": str(tenant_b.offering_id),
                "subject_party_id": str(tenant_a.subject_party_id),
            },
            headers={**headers_a, "Idempotency-Key": f"foreign-offering-{uuid4().hex}"},
        )
        foreign_party_join = await client.post(
            "/v1/waitlist",
            json={
                "offering_id": str(tenant_a.offering_id),
                "subject_party_id": str(tenant_b.subject_party_id),
            },
            headers={**headers_a, "Idempotency-Key": f"foreign-party-{uuid4().hex}"},
        )
        assert 400 <= foreign_offering_join.status_code < 500
        assert 400 <= foreign_party_join.status_code < 500

        owner_read = await client.get(f"/v1/waitlist/{entry_b_id}", headers=headers_b)
        assert owner_read.status_code == 200
        assert owner_read.json()["status"] == "active"
        assert owner_read.json()["revision"] == entry_b_revision

    foreign_rows = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.waitlist_entries
        WHERE organization_id = %s
          AND (
              offering_id = %s
              OR subject_party_id = %s
          )
        """,
        (tenant_a.organization_id, tenant_b.offering_id, tenant_b.subject_party_id),
    ).fetchone()
    assert foreign_rows == (0,)
