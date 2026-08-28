from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from httpx import AsyncClient, Response

from .f5_extend_day_support import (
    assignment_recovery_exception_count,
    location_recovery_exception_count,
)
from .f5_scheduled_assessment_support import lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth

assignment_exception_count = assignment_recovery_exception_count
location_exception_count = location_recovery_exception_count


class ExtendCall(TypedDict):
    assignment_id: UUID
    window: tuple[datetime, datetime]
    owner_revisions: tuple[int, int]


def error_code(response: Response) -> object:
    return response.json()["error"]["code"]


async def reproject(
    handler: Any, conn: PgConnection, sandbox: TenantSandbox, target_revision: int
) -> None:
    applied = await handler.handle(lease_reassessment(conn, sandbox, target_revision))
    assert applied.applied is True


def intake_state(conn: PgConnection, sandbox: TenantSandbox) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT accepting,revision FROM request_engine.service_queue_intake_controls "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def queue_entry_count(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def incident_facts(conn: PgConnection, sandbox: TenantSandbox) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT id,status,source_revision,revision"
            " FROM request_engine.operational_recovery_incidents"
            " WHERE organization_id=%s AND service_queue_id=%s",
            (sandbox.organization_id, sandbox.queue_id),
        ).fetchall()
    ]


def action_rows(
    conn: PgConnection,
    sandbox: TenantSandbox,
    incident_id: UUID,
) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT action_kind,status,principal_id,expected_source_revision,"
            "owner_steps,failure_code,idempotency_key"
            " FROM request_engine.operational_recovery_actions"
            " WHERE organization_id=%s AND incident_id=%s ORDER BY created_at,id",
            (sandbox.organization_id, incident_id),
        ).fetchall()
    ]


def seed_future_hours_exception(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        "INSERT INTO request_engine.location_hours_exceptions "
        "(organization_id,location_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp()+interval '2 days',"
        "clock_timestamp()+interval '2 days 1 hour','[)'),'available',"
        "'planned extended hours',true)",
        (sandbox.organization_id, sandbox.location_id),
    )


async def post_intake_control(
    client: AsyncClient,
    sandbox: TenantSandbox,
    incident_id: UUID,
    *,
    body: Mapping[str, object],
    key: str,
) -> Response:
    return await client.post(
        f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
        json=dict(body),
        headers=auth(sandbox, idempotency_key=key),
    )


async def post_extend_day(
    client: AsyncClient,
    sandbox: TenantSandbox,
    incident_id: UUID,
    *,
    source_revision: int,
    assignment_id: UUID,
    window: tuple[datetime, datetime],
    owner_revisions: tuple[int, int],
    key: str,
) -> Response:
    return await client.post(
        f"/v1/operational-recovery/incidents/{incident_id}/extend-day",
        json={
            "expected_source_revision": source_revision,
            "authority_party_id": str(sandbox.party_id),
            "assignment_id": str(assignment_id),
            "start_at": window[0].isoformat(),
            "end_at": window[1].isoformat(),
            "expected_location_operational_revision": owner_revisions[0],
            "expected_resource_availability_revision": owner_revisions[1],
            "reason": "recover commitments beyond closing time",
        },
        headers=auth(sandbox, idempotency_key=key),
    )


async def walk_in(client: AsyncClient, sandbox: TenantSandbox, subject_id: UUID) -> Response:
    return await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(subject_id)},
        headers=auth(sandbox, idempotency_key=f"walk-in-{uuid4().hex}"),
    )
