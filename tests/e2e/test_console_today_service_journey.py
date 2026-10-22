"""A fresh clinic owner serves a booked customer end to end from the Today front desk.

Journey (all through the real console and the real runtime on PostgreSQL 18):
set up the clinic -> register a customer -> book -> check in -> call next ->
start service with the doctor offered for the queue's location -> finish.

The owner is a real native identity of an organization provisioned with the
current fresh-organization controller policy (tenant-controller-v9), so the
grants and Party representations used are the ones a real owner holds.

Oracles: queue entry and service session rows read with the admin connection,
and the owner's own day-board and staff reads made directly against the runtime
(never values rendered or computed by the console).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import LiteralString
from uuid import UUID

import pytest

from request_engine.platform.db.session import SessionFactory

from .console_owner_support import csrf, owner_console
from .native_provisioning_support import PgConnection

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_POLICY = "tenant-controller-v9"
_DAY = "2030-01-07"
_HOURS = {f"day{day}_{part}": value for day in range(5) for part, value in (
    ("open", "on"), ("start", "08:00"), ("end", "17:00"))}  # fmt: skip


def _one(
    conn: PgConnection, query: LiteralString, params: tuple[object, ...]
) -> tuple[object, ...]:
    rows = conn.execute(query, params).fetchall()
    assert len(rows) == 1, rows
    return tuple(rows[0])


@pytest.mark.asyncio
async def test_owner_calls_starts_and_finishes_a_booked_customer_from_today(
    tmp_path: Path,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    conn = e2e_admin_conn
    async with owner_console(tmp_path, conn, e2e_session_factory, policy=_POLICY) as owner:
        browser, org = owner.browser, owner.organization_id
        setup = f"/tenants/{org}/setup"
        token = csrf((await browser.get(setup)).text)
        location_saved = await browser.post(
            f"{setup}/location",
            data={
                "csrf_token": token,
                "_intent_id": "today-service-location",
                "display_name": "Sede Gazcue",
                "address_line1": "Av. Independencia 123",
                "locality": "Santo Domingo",
                "administrative_area": "Distrito Nacional",
                "country_code": "DO",
                **_HOURS,
            },
        )
        assert location_saved.status_code == 303, location_saved.text
        service_saved = await browser.post(
            f"{setup}/services",
            data={
                "csrf_token": token,
                "_intent_id": "today-service-offering",
                "display_name": "Consulta general",
                "duration_minutes": "30",
                "price": "1500",
                "currency": "DOP",
            },
        )
        assert service_saved.status_code == 303, service_saved.text
        providers = await browser.get(f"{setup}?step=providers")
        capability = re.search(r'name="capability_id" value="([0-9a-f-]+)"', providers.text)
        location = re.search(r'<option value="([0-9a-f-]+)"[^>]*>Sede Gazcue', providers.text)
        assert capability is not None and location is not None, providers.text
        location_id = UUID(location.group(1))
        provider_saved = await browser.post(
            f"{setup}/providers",
            data={
                "csrf_token": token,
                "_intent_id": "today-service-provider",
                "display_name": "Dra. Ana Pérez",
                "kind": "doctor",
                "location_id": str(location_id),
                "capability_id": capability.group(1),
                **_HOURS,
            },
        )
        assert provider_saved.status_code == 303, provider_saved.text
        queue_saved = await browser.post(
            f"{setup}/queue",
            data={
                "csrf_token": token,
                "_intent_id": "today-service-queue",
                "display_name": "Sala de espera",
                "location_id": str(location_id),
            },
        )
        assert queue_saved.status_code == 303, queue_saved.text
        (resource_id,) = _one(
            conn, "SELECT id FROM request_engine.resources WHERE organization_id=%s", (org,)
        )
        (queue_id,) = _one(
            conn, "SELECT id FROM request_engine.service_queues WHERE organization_id=%s", (org,)
        )
        (version_id,) = _one(
            conn,
            "SELECT v.id FROM request_engine.offering_versions v "
            "JOIN request_engine.offerings o ON o.id = v.offering_id WHERE o.organization_id=%s",
            (org,),
        )

        visit = await browser.get(f"/tenants/{org}/today/visit")
        registered = await browser.post(
            f"/tenants/{org}/today/visit/register",
            data={
                "csrf_token": csrf(visit.text),
                "_intent_id": "today-service-register",
                "display_name": "Altagracia Servicio",
                "phone": "8095550144",
            },
        )
        assert registered.status_code == 303, registered.text
        match = re.search(r"/today/visit/([0-9a-f-]+)\?", registered.headers["location"])
        assert match is not None
        party_id = UUID(match.group(1))
        slots = await browser.get(
            f"/tenants/{org}/today/visit/{party_id}",
            params={"offering_version_id": str(version_id), "day": _DAY},
        )
        options = re.findall(r'name="option_id" value="([^"]+)"', slots.text)
        assert options, slots.text
        booked = await browser.post(
            f"/tenants/{org}/today/visit/{party_id}/book",
            data={
                "csrf_token": csrf(slots.text),
                "_intent_id": "today-service-book",
                "option_id": html.unescape(options[0]),
            },
        )
        assert booked.status_code == 303, booked.text
        (reservation_id,) = _one(
            conn,
            "SELECT id FROM request_engine.reservations WHERE subject_party_id=%s",
            (party_id,),
        )

        today = await browser.get(f"/tenants/{org}/today")
        checked_in = await browser.post(
            f"/tenants/{org}/today/appointments/{reservation_id}/check-in",
            data={
                "csrf_token": csrf(today.text),
                "_intent_id": "today-service-check-in",
                "queue_id": str(queue_id),
                "subject_party_id": str(party_id),
            },
        )
        assert checked_in.status_code == 303, checked_in.text
        called = await browser.post(
            f"/tenants/{org}/today/queues/{queue_id}/call-next",
            data={"csrf_token": csrf(today.text), "_intent_id": "today-service-call"},
        )
        assert called.status_code == 303, called.text
        assert called.headers["location"] == f"/tenants/{org}/today?done=called"

        # The owner day board reports arrival as the active queue entry; the
        # reservation's own attendance check-in stays empty (why Today counts both).
        headers = {"Authorization": f"Bearer {owner.token}", "X-RE-Organization-ID": str(org)}
        board = await owner.runtime.get(
            "/v1/appointments/day-board",
            params={"window_start": f"{_DAY}T00:00:00+00:00", "window_end": "2030-01-08T00:00:00Z"},
            headers=headers,
        )
        assert board.status_code == 200, board.text
        (row,) = [item for item in board.json() if item["reservation_id"] == str(reservation_id)]
        assert row["checked_in_at"] is None
        assert (row["active_queue_entry_count"], row["queue_entry_status"]) == (1, "called")

        # Today offers Start service with the doctor assigned to the queue location.
        page = await browser.get(f"/tenants/{org}/today?done=called")
        assert page.status_code == 200, page.text
        (entry_id,) = _one(
            conn,
            "SELECT id FROM request_engine.queue_entries WHERE reservation_id=%s",
            (reservation_id,),
        )
        assert f"/today/entries/{entry_id}/start-service" in page.text, page.text
        choice = f"{resource_id}@{location_id}"
        assert f'value="{choice}">Dra. Ana Pérez</option>' in html.unescape(page.text)
        revision = re.search(
            rf'/entries/{entry_id}/start-service">.*?name="expected_queue_revision" value="(\d+)"',
            page.text,
            re.S,
        )
        assert revision is not None
        start_form = {
            "csrf_token": csrf(page.text),
            "_intent_id": "today-service-start",
            "staff": choice,
            "expected_queue_revision": revision.group(1),
        }
        started = await browser.post(
            f"/tenants/{org}/today/entries/{entry_id}/start-service", data=start_form
        )
        assert started.status_code == 303, started.text
        assert started.headers["location"] == f"/tenants/{org}/today?done=started"
        # A browser replay of the same form intent is the owner's idempotent replay.
        replay = await browser.post(
            f"/tenants/{org}/today/entries/{entry_id}/start-service", data=start_form
        )
        assert replay.status_code == 303, replay.text
        session_id, session_status, used_resource, used_location = _one(
            conn,
            "SELECT id, status, resource_id, location_id FROM request_engine.service_sessions "
            "WHERE queue_entry_id=%s",
            (entry_id,),
        )
        assert (session_status, used_resource, used_location) == (
            "active",
            resource_id,
            location_id,
        )

        # In service: Today now offers Finish for that session, not Start.
        serving = await browser.get(f"/tenants/{org}/today?done=started")
        assert f"/today/sessions/{session_id}/complete" in serving.text, serving.text
        assert f"/today/entries/{entry_id}/start-service" not in serving.text
        finish_revision = re.search(
            rf'/sessions/{session_id}/complete">.*?name="expected_revision" value="(\d+)"',
            serving.text,
            re.S,
        )
        assert finish_revision is not None
        finished = await browser.post(
            f"/tenants/{org}/today/sessions/{session_id}/complete",
            data={
                "csrf_token": csrf(serving.text),
                "_intent_id": "today-service-finish",
                "expected_revision": finish_revision.group(1),
            },
        )
        assert finished.status_code == 303, finished.text
        assert finished.headers["location"] == f"/tenants/{org}/today?done=completed"

        # After the visit the owner day board still reports it as a served visit
        # (Today renders only the real current business day, so the "Atendido a las"
        # rendering itself is proven by the console unit tests).
        served_board = await owner.runtime.get(
            "/v1/appointments/day-board",
            params={"window_start": f"{_DAY}T00:00:00+00:00", "window_end": "2030-01-08T00:00:00Z"},
            headers=headers,
        )
        assert served_board.status_code == 200, served_board.text
        (served,) = [
            item for item in served_board.json() if item["reservation_id"] == str(reservation_id)
        ]
        assert served["active_queue_entry_count"] == 0
        assert served["served_queue_entry_id"] == str(entry_id)
        assert served["served_at"] is not None and served["visit_arrived_at"] is not None

    session_row = _one(
        conn,
        "SELECT status, completed_at IS NOT NULL FROM request_engine.service_sessions "
        "WHERE queue_entry_id=%s",
        (entry_id,),
    )
    assert session_row == ("completed", True)
    entry_row = _one(
        conn, "SELECT status FROM request_engine.queue_entries WHERE id=%s", (entry_id,)
    )
    assert entry_row == ("completed",)
