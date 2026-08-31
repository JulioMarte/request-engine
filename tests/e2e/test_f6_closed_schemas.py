from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import LiteralString
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.adversarial]

_INJECTED_FIELDS = (
    "authority_party_id",
    "organization_id",
    "principal_id",
    "owner",
    "operation",
    "expected_revision",
)


def _recovery_body() -> dict[str, object]:
    return {"service_queue_id": str(uuid4()), "search_days": 7}


def _intake_body() -> dict[str, object]:
    return {
        "service_queue_id": str(uuid4()),
        "accepting": False,
        "expected_intake_revision": 0,
        "reason": "probe",
    }


def _extend_body() -> dict[str, object]:
    start = datetime.now(UTC)
    return {
        "assignment_id": str(uuid4()),
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(),
        "expected_resource_availability_revision": 0,
        "reason": "probe",
    }


def _org_leak(table: LiteralString) -> tuple[LiteralString, str]:
    return (f"SELECT count(*) FROM request_engine.{table} WHERE organization_id=%s", "organization")


def _closed_write_cases() -> tuple[
    tuple[str, Callable[[], dict[str, object]], LiteralString, str], ...
]:
    return (
        ("/recovery/proposals", _recovery_body, *_org_leak("operational_recovery_proposals")),
        (
            "/queues/intake-control",
            _intake_body,
            "SELECT count(*) FROM request_engine.service_queue_intake_controls "
            "WHERE service_queue_id=%s",
            "service_queue_id",
        ),
        (
            "/assignments/day-extensions",
            _extend_body,
            *_org_leak("resource_location_schedule_exceptions"),
        ),
    )


_CASES = _closed_write_cases()


@pytest.mark.parametrize(("path", "body_builder", "leak_query", "leak_param"), _CASES)
async def test_f6_write_rejects_injected_and_unknown_fields(
    path: str,
    body_builder: Callable[[], dict[str, object]],
    leak_query: LiteralString,
    leak_param: str,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, f"f6-closed-schema-{uuid4().hex[:8]}")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        for field in _INJECTED_FIELDS:
            body = {**body_builder(), field: "00000000-0000-4000-8000-000000000009"}
            key = f"f6-closed-{uuid4().hex}"
            response = await client.post(
                f"/v1/operational-copilot/tools{path}",
                json=body,
                headers=auth(sandbox, idempotency_key=key),
            )
            assert response.status_code == 422, (field, response.text)
            assert response.json()["error"]["code"] == "validation_failed", response.text
            leaked = e2e_admin_conn.execute(
                leak_query,
                (
                    (sandbox.organization_id,)
                    if leak_param == "organization"
                    else (str(body["service_queue_id"]),)
                ),
            ).fetchone()
            assert leaked == (0,), field
