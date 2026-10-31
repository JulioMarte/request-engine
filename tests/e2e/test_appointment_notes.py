"""Appointment notes: append-only, attributed staff notes on a Reservation.

Protected guarantee: INV-APPOINTMENT-NOTES-001.

Protected risks (plausible regressions that must turn this red):

* a note written without ``appointments.annotate`` or read without the staff
  read ``appointments.day_board`` (a customer holding only subject-scoped
  ``appointments.read`` must never see staff notes, also not through
  ``appointments_read``);
* another organization adding/reading notes on a foreign Reservation, or the
  view leaking rows under the runtime role;
* the author kind taken from the caller instead of the authoritative principal,
  or the staff display name not resolved;
* idempotent replay creating a second note, or a reused key with a different
  body accepted;
* a correction pointing at a note of a different appointment;
* notes refused on a cancelled appointment, or a note advancing the Reservation
  revision (which would break a concurrent reschedule/cancel);
* list order/paging wrong (newest first, stable keyset, cursor bound to the
  appointment);
* day board / calendar / read counts and latest-note indicator wrong;
* the change signal missing from the ``day_board`` feed, or carrying note text;
* the table accepting UPDATE/DELETE, a mismatched author kind, or granting the
  runtime role UPDATE.

Execution boundary: owner HTTP operations on the real application and the
least-privilege runtime role on PostgreSQL 18. Oracles: authoritative
``reservation_notes`` / ``reservations`` / ``outbox_messages`` rows read with the
admin connection, never the notes view or reader under test.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from request_engine.entrypoints.http.change_topics import ChangeTopicTable
from request_engine.platform.changes.postgres import PostgresChangeFeedReader
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import (
    OVERRIDE_CAPABILITIES,
    TenantSandbox,
    actor_for,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

DAY = datetime(2030, 1, 7, tzinfo=UTC)
STAFF = frozenset({"appointments.day_board", "appointments.annotate"})


def _bearer(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _named_human_staff(conn: PgConnection, sandbox: TenantSandbox, name: str) -> UUID:
    """A valid active human staff member with a directory display name (prerequisite)."""

    principal_id, party_id, binding_id, membership_id = uuid4(), uuid4(), uuid4(), uuid4()
    authority_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"notes-staff:{authority_id}"),
    )
    conn.execute(
        "INSERT INTO request_engine.principals "
        "(id, organization_id, principal_plane, principal_kind, external_subject) "
        "VALUES (%s, %s, 'tenant', 'human', %s)",
        (principal_id, sandbox.organization_id, f"notes-human-{principal_id}"),
    )
    conn.execute(
        "INSERT INTO request_engine.parties (id, organization_id, party_kind, display_name) "
        "VALUES (%s, %s, 'person', %s)",
        (party_id, sandbox.organization_id, name),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings (id, organization_id, principal_id, "
        "principal_plane, identity_authority_id, subject_id, status) "
        "VALUES (%s, %s, %s, 'tenant', %s, %s, 'active')",
        (binding_id, sandbox.organization_id, principal_id, authority_id, str(uuid4())),
    )
    conn.execute(
        "INSERT INTO request_engine.staff_memberships (id, organization_id, principal_id, "
        "identity_binding_id, authority_anchor_party_id, status, established_by_principal_id, "
        "provenance_kind, provenance_reference, activated_at) "
        "VALUES (%s, %s, %s, %s, %s, 'active', %s, 'staff_invitation', %s, clock_timestamp())",
        (
            membership_id,
            sandbox.organization_id,
            principal_id,
            binding_id,
            party_id,
            principal_id,
            f"notes:{uuid4().hex}",
        ),
    )
    conn.execute(
        "INSERT INTO request_engine.staff_member_profiles (organization_id, membership_id, "
        "display_name, revision, updated_by_principal_id, provenance_reference) "
        "VALUES (%s, %s, %s, 1, %s, 'notes:profile')",
        (sandbox.organization_id, membership_id, name, principal_id),
    )
    return principal_id


async def _book(client: AsyncClient, sandbox: TenantSandbox, token: str, index: int) -> Any:
    slots = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": DAY.replace(hour=13).isoformat(),
            "window_end": DAY.replace(hour=16).isoformat(),
        },
        headers=_bearer(token),
    )
    assert slots.status_code == 200, slots.text
    booked = await client.post(
        "/v1/appointments",
        json={
            "option_id": slots.json()[index]["option_id"],
            "subject_party_id": str(sandbox.party_id),
        },
        headers=_bearer(token, f"notes-book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    return booked.json()


def _db_notes(conn: PgConnection, reservation_id: str) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT id, body, author_principal_id, author_principal_kind, supersedes_note_id "
        "FROM request_engine.reservation_notes WHERE reservation_id = %s "
        "ORDER BY created_at DESC, id DESC",
        (UUID(reservation_id),),
    ).fetchall()


def _revision(conn: PgConnection, reservation_id: str) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.reservations WHERE id = %s", (UUID(reservation_id),)
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.asyncio
async def test_staff_notes_are_attributed_idempotent_paged_counted_and_tenant_isolated(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "notes")
    other = seed_tenant_sandbox(e2e_admin_conn, "notes-other")
    human_id = _named_human_staff(e2e_admin_conn, clinic, "María Recepción")
    base = actor_for(clinic).capabilities
    actors = {
        "agent": ActorContext(clinic.organization_id, clinic.principal_id, base | STAFF),
        "human": ActorContext(clinic.organization_id, human_id, base | STAFF),
        "reader": ActorContext(
            clinic.organization_id, clinic.principal_id, base | {"appointments.day_board"}
        ),
        # Subject-scoped customer-like caller: appointments.read via Party authority only.
        "customer": ActorContext(
            clinic.organization_id, clinic.principal_id, base - OVERRIDE_CAPABILITIES
        ),
        "foreign": ActorContext(other.organization_id, other.principal_id, base | STAFF),
    }
    feed = PostgresChangeFeedReader(e2e_session_factory)
    topics = ChangeTopicTable()
    async with client_with_actors(e2e_session_factory, actors) as client:
        first = await _book(client, clinic, "agent", 0)
        second = await _book(client, clinic, "agent", -1)
        await _book(client, other, "foreign", 0)
        rid = first["id"]
        snapshot = await feed.current_snapshot(clinic.organization_id)
        revision_before = _revision(e2e_admin_conn, rid)

        key = f"notes-add-{uuid4().hex}"
        created = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "  Viene con su hijo\r\n  "},
            headers=_bearer("human", key),
        )
        replayed = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "  Viene con su hijo\r\n  "},
            headers=_bearer("human", key),
        )
        reused_key = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "Otro texto"},
            headers=_bearer("human", key),
        )
        correction = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={
                "body": "Viene con su hija, no hijo",
                "supersedes_note_id": created.json()["note_id"],
            },
            headers=_bearer("agent", f"notes-add-{uuid4().hex}"),
        )
        cancelled = await client.post(
            f"/v1/appointments/{rid}/cancel",
            json={"expected_revision": first["revision"], "reason": "notes proof"},
            headers=_bearer("agent", f"notes-cancel-{uuid4().hex}"),
        )
        after_cancel = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "Canceló: llamó para avisar\nque está de viaje"},
            headers=_bearer("agent", f"notes-add-{uuid4().hex}"),
        )
        # Refusals.
        empty = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "   "},
            headers=_bearer("agent", f"notes-bad-{uuid4().hex}"),
        )
        too_long = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "x" * 1001},
            headers=_bearer("agent", f"notes-bad-{uuid4().hex}"),
        )
        other_note = await client.post(
            f"/v1/appointments/{second['id']}/notes",
            json={"body": "Pidió factura con RNC"},
            headers=_bearer("agent", f"notes-add-{uuid4().hex}"),
        )
        cross_reservation = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "corrige otra cita", "supersedes_note_id": other_note.json()["note_id"]},
            headers=_bearer("agent", f"notes-bad-{uuid4().hex}"),
        )
        unknown = await client.post(
            f"/v1/appointments/{uuid4()}/notes",
            json={"body": "nadie"},
            headers=_bearer("agent", f"notes-bad-{uuid4().hex}"),
        )
        without_key = await client.post(
            f"/v1/appointments/{rid}/notes", json={"body": "sin clave"}, headers=_bearer("agent")
        )
        denied_write = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "sin permiso"},
            headers=_bearer("reader", f"notes-bad-{uuid4().hex}"),
        )
        foreign_write = await client.post(
            f"/v1/appointments/{rid}/notes",
            json={"body": "de otra clínica"},
            headers=_bearer("foreign", f"notes-bad-{uuid4().hex}"),
        )
        # Reads.
        page_one = await client.get(
            f"/v1/appointments/{rid}/notes", params={"limit": "2"}, headers=_bearer("reader")
        )
        page_two = await client.get(
            f"/v1/appointments/{rid}/notes",
            params={"limit": "2", "after": page_one.json()["next_cursor"]},
            headers=_bearer("reader"),
        )
        wrong_cursor = await client.get(
            f"/v1/appointments/{second['id']}/notes",
            params={"after": page_one.json()["next_cursor"]},
            headers=_bearer("reader"),
        )
        customer_list = await client.get(
            f"/v1/appointments/{rid}/notes", headers=_bearer("customer")
        )
        foreign_list = await client.get(f"/v1/appointments/{rid}/notes", headers=_bearer("foreign"))
        staff_read = await client.get(f"/v1/appointments/{rid}", headers=_bearer("reader"))
        customer_read = await client.get(f"/v1/appointments/{rid}", headers=_bearer("customer"))
        board = await client.get(
            "/v1/appointments/day-board",
            params={
                "window_start": DAY.isoformat(),
                "window_end": DAY.replace(hour=23).isoformat(),
            },
            headers=_bearer("reader"),
        )
        calendar = await client.get(
            "/v1/appointments/calendar",
            params={"window_start": DAY.isoformat(), "window_end": DAY.replace(day=8).isoformat()},
            headers=_bearer("reader"),
        )
        delta = await feed.read_since(
            clinic.organization_id,
            snapshot,
            patterns=topics.patterns(frozenset({"day_board"})),
            limit=100,
        )

    # Creation, attribution and replay.
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["body"] == "Viene con su hijo"
    assert (note["author_kind"], note["author_display_name"]) == ("human", "María Recepción")
    assert note["author_principal_id"] == str(human_id)
    assert replayed.status_code == 201 and replayed.json() == note
    assert reused_key.status_code == 409, reused_key.text
    assert correction.status_code == 201, correction.text
    assert correction.json()["author_kind"] == "agent"
    assert correction.json()["supersedes_note_id"] == note["note_id"]
    assert cancelled.status_code == 200, cancelled.text
    assert after_cancel.status_code == 201, after_cancel.text

    # Independent oracle: exactly three facts on the appointment, newest first.
    rows = _db_notes(e2e_admin_conn, rid)
    assert [(r[1], r[3]) for r in rows] == [
        ("Canceló: llamó para avisar\nque está de viaje", "agent"),
        ("Viene con su hija, no hijo", "agent"),
        ("Viene con su hijo", "human"),
    ]
    assert rows[1][4] == UUID(note["note_id"]) and rows[2][2] == human_id
    # Notes never advanced the revision: only the cancel did (by exactly one).
    assert _revision(e2e_admin_conn, rid) == revision_before + 1 == cancelled.json()["revision"]

    # Refusals leave no rows behind.
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "appointment_note_invalid"
    assert too_long.status_code == 422, too_long.text
    assert cross_reservation.status_code == 422
    assert cross_reservation.json()["error"]["code"] == "appointment_note_supersedes_invalid"
    assert unknown.status_code == 404, unknown.text
    assert without_key.status_code == 422, without_key.text
    assert denied_write.status_code == 403, denied_write.text
    assert foreign_write.status_code == 404, foreign_write.text
    assert len(_db_notes(e2e_admin_conn, rid)) == 3
    assert len(_db_notes(e2e_admin_conn, second["id"])) == 1

    # Paged list, newest first, same order as the authoritative rows.
    assert page_one.status_code == 200 and page_two.status_code == 200
    listed = page_one.json()["items"] + page_two.json()["items"]
    assert [item["note_id"] for item in listed] == [str(r[0]) for r in rows]
    assert page_two.json()["next_cursor"] is None
    assert listed[-1]["author_display_name"] == "María Recepción"
    assert wrong_cursor.status_code == 422
    assert customer_list.status_code == 403
    assert foreign_list.status_code == 404
    assert "hijo" not in foreign_list.text and "hijo" not in foreign_write.text

    # Indicators without N+1 calls.
    latest = {
        "excerpt": "Canceló: llamó para avisar que está de viaje",
        "author_kind": "agent",
        "created_at": listed[0]["created_at"],
    }
    assert staff_read.status_code == 200
    assert (staff_read.json()["note_count"], staff_read.json()["latest_note"]) == (3, latest)
    assert customer_read.status_code == 200, customer_read.text
    assert customer_read.json()["note_count"] is None
    assert customer_read.json()["latest_note"] is None
    assert "hijo" not in customer_read.text
    by_board = {item["reservation_id"]: item for item in board.json()}
    assert (by_board[rid]["note_count"], by_board[rid]["latest_note"]) == (3, latest)
    assert (by_board[second["id"]]["note_count"], by_board[second["id"]]["latest_note"]) == (
        1,
        {
            "excerpt": "Pidió factura con RNC",
            "author_kind": "agent",
            "created_at": other_note.json()["created_at"],
        },
    )
    by_calendar = {item["reservation_id"]: item for item in calendar.json()["items"]}
    assert by_calendar[rid]["note_count"] == 3
    assert by_calendar[second["id"]]["note_count"] == 1

    # Change signal: one PII-free day_board fact per note.
    outbox = e2e_admin_conn.execute(
        "SELECT payload FROM request_engine.outbox_messages "
        "WHERE aggregate_id = %s AND event_type = 'reservation.note_added.v1'",
        (UUID(rid),),
    ).fetchall()
    assert len(outbox) == 3
    assert all("body" not in row[0] and "hij" not in str(row[0]) for row in outbox)
    note_events = [
        event
        for row in delta.rows
        if row.event_type == "reservation.note_added.v1"
        for event in topics.events_for(row)
    ]
    assert {(e.topic, str(e.resource_id)) for e in note_events} == {
        ("day_board", rid),
        ("day_board", second["id"]),
    }
    assert len(note_events) == 4
    audit = e2e_admin_conn.execute(
        "SELECT details FROM request_engine.audit_records "
        "WHERE aggregate_id = %s AND command_name = 'appointments.annotate'",
        (UUID(rid),),
    ).fetchall()
    assert len(audit) == 3 and all("hij" not in str(row[0]) for row in audit)

    # Runtime-role RLS: the other tenant sees no note rows of the clinic.
    async with tenant_transaction(e2e_session_factory, other.organization_id) as session:
        leaked_view = (
            await session.execute(
                text(
                    "SELECT count(*) FROM request_read.reservation_notes_v1 "
                    "WHERE reservation_id = :r"
                ),
                {"r": rid},
            )
        ).scalar_one()
        leaked_table = (
            await session.execute(text("SELECT count(*) FROM request_engine.reservation_notes"))
        ).scalar_one()
    assert (leaked_view, leaked_table) == (0, 0)


@pytest.mark.asyncio
async def test_note_table_is_append_only_author_checked_and_least_privilege(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "notes-backstop")
    actors = {"agent": actor_for(clinic)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        booked = await _book(client, clinic, "agent", 0)
    reservation = (UUID(booked["id"]),)
    insert = (
        "INSERT INTO request_engine.reservation_notes (organization_id, reservation_id, body, "
        "author_principal_id, author_principal_kind) VALUES (%s, %s, %s, %s, %s) RETURNING id"
    )
    values = (clinic.organization_id, reservation[0], "nota", clinic.principal_id)
    # The sandbox principal is an agent: claiming "human" is refused by the trigger.
    with pytest.raises(psycopg.errors.CheckViolation):
        e2e_admin_conn.execute(insert, (*values, "human"))
    created = e2e_admin_conn.execute(insert, (*values, "agent")).fetchone()
    assert created is not None
    for statement in (
        "UPDATE request_engine.reservation_notes SET body = 'editada' WHERE id = %s",
        "DELETE FROM request_engine.reservation_notes WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            e2e_admin_conn.execute(statement, (created[0],))
    for bad_body in ("  padded  ", "", "x" * 1001, "bell\x07"):
        with pytest.raises(psycopg.errors.CheckViolation):
            e2e_admin_conn.execute(
                insert,
                (clinic.organization_id, reservation[0], bad_body, clinic.principal_id, "agent"),
            )
    privileges = e2e_admin_conn.execute(
        "SELECT has_table_privilege('request_engine_app', 'request_engine.reservation_notes', p) "
        "FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p"
    ).fetchall()
    assert [row[0] for row in privileges] == [True, True, False, False, False]
    view = e2e_admin_conn.execute(
        "SELECT c.reloptions, has_table_privilege('request_engine_app', c.oid, 'INSERT'), "
        "has_table_privilege('public', c.oid, 'SELECT') FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'request_read' AND c.relname = 'reservation_notes_v1'"
    ).fetchone()
    assert view is not None
    assert "security_invoker=true" in (view[0] or []) and view[1:] == (False, False)
    forced = e2e_admin_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_catalog.pg_class "
        "WHERE oid = 'request_engine.reservation_notes'::regclass"
    ).fetchone()
    assert forced == (True, True)
