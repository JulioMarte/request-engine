"""Real app-role projection of committed staff audit, never a fabricated command result."""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from test_staff_membership_lifecycle import (
    invite_active_staff,
    new_staff_native_identity,
    provision_staff_root,
)

from request_engine.modules.tenancy.adapters.db.staff_history_reader import (
    PostgresStaffHistoryReader,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_reader import (
    PostgresStaffMembershipReader,
)
from request_engine.modules.tenancy.api.staff_history_reads import add_staff_history_reads
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.modules.tenancy.application.commands.staff_membership import (
    ReplaceStaffAuthorityCommand,
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
    UpdateStaffProfileCommand,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipForbidden,
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
)
from request_engine.modules.tenancy.application.queries.staff_history import ListStaffHistoryQuery
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


def _world(conn: Connection[Any]) -> tuple[ActorContext, UUID]:
    org, party, root, _, _ = provision_staff_root(conn)
    authority, identity, _ = new_staff_native_identity(conn)
    member, _, _ = invite_active_staff(
        conn,
        organization_id=org,
        root_id=root,
        party_id=party,
        authority_id=authority,
        native_identity_id=identity,
    )
    return ActorContext(
        organization_id=org,
        principal_id=root,
        capabilities=frozenset({"staff.read", "staff.manage_membership", "staff.manage_authority"}),
    ), member


def _durable_counts(conn: Connection[Any]) -> tuple[object, ...]:
    row = conn.execute("""
        SELECT (SELECT count(*) FROM request_engine.audit_records),
               (SELECT count(*) FROM request_engine.idempotency_records),
               (SELECT count(*) FROM request_engine.staff_memberships),
               (SELECT count(*) FROM request_engine.principal_authority_grants),
               (SELECT count(*) FROM request_engine.staff_member_profiles)
    """).fetchone()
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_history_projects_real_commands_without_duplicates_or_private_payload(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    history = PostgresStaffHistoryReader(command_session_factory)
    membership_reader = PostgresStaffMembershipReader(command_session_factory)
    assert (await history.list_history(actor, ListStaffHistoryQuery(member))).items == ()
    command = UpdateStaffProfileCommand(
        member, "Private member label", 0, "private:provenance", uuid4().hex
    )
    await writer.update_staff_profile(actor, command)
    await writer.update_staff_profile(actor, command)
    await writer.update_staff_profile(
        actor,
        replace(
            command, display_name=None, expected_profile_revision=1, idempotency_key=uuid4().hex
        ),
    )
    current = await membership_reader.read_membership(actor, member)
    await writer.replace_staff_authority(
        actor,
        ReplaceStaffAuthorityCommand(
            member,
            current.authority_revision,
            (),
            "private:authority",
            uuid4().hex,
        ),
    )
    await writer.transition_staff_membership(
        actor,
        TransitionStaffMembershipCommand(
            member,
            current.membership_revision,
            StaffMembershipTargetStatus.SUSPENDED,
            "private:status",
            uuid4().hex,
        ),
    )
    oracle = admin_conn.execute(
        "SELECT id,command_name,actor_principal_id,created_at FROM request_engine.audit_records "
        "WHERE aggregate_id=%s ORDER BY created_at DESC,id DESC",
        (member,),
    ).fetchall()
    assert len(oracle) == 4
    before = _durable_counts(admin_conn)
    first = await history.list_history(actor, ListStaffHistoryQuery(member, limit=2))
    second = await history.list_history(
        actor, ListStaffHistoryQuery(member, after=first.next_cursor, limit=2)
    )
    assert first.next_cursor == first.items[-1].event_id
    assert second.next_cursor is None  # Exact last page: no misleading extra link.
    entries = first.items + second.items
    assert [
        (x.event_id, x.command_name, x.actor_principal_id, x.occurred_at) for x in entries
    ] == oracle
    assert [x.revision_kind for x in entries] == ["membership", "authority", "profile", "profile"]
    assert [(x.revision_before, x.revision_after) for x in entries[-2:]] == [(1, 2), (0, 1)]
    assert "private:" not in repr(entries) and "Private member label" not in repr(entries)
    assert _durable_counts(admin_conn) == before


@pytest.mark.asyncio
async def test_history_denies_foreign_target_foreign_cursor_and_revoked_reader(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    foreign_actor, foreign_member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    reader = PostgresStaffHistoryReader(command_session_factory)
    await writer.update_staff_profile(
        foreign_actor,
        UpdateStaffProfileCommand(
            foreign_member,
            "Foreign label",
            0,
            "test",
            uuid4().hex,
        ),
    )
    foreign_page = await reader.list_history(foreign_actor, ListStaffHistoryQuery(foreign_member))
    root_membership = admin_conn.execute(
        "SELECT id FROM request_engine.staff_memberships WHERE principal_id=%s",
        (actor.principal_id,),
    ).fetchone()
    assert root_membership is not None
    await writer.update_staff_profile(
        actor, UpdateStaffProfileCommand(root_membership[0], "Root label", 0, "test", uuid4().hex)
    )
    root_page = await reader.list_history(actor, ListStaffHistoryQuery(root_membership[0]))
    before = _durable_counts(admin_conn)
    for target in (foreign_member, uuid4()):
        with pytest.raises(StaffMembershipNotFound):
            await reader.list_history(actor, ListStaffHistoryQuery(target))
    for cursor in (foreign_page.items[0].event_id, root_page.items[0].event_id, uuid4()):
        with pytest.raises(StaffMembershipInputInvalid, match="cursor is invalid"):
            await reader.list_history(actor, ListStaffHistoryQuery(member, after=cursor))
    with pytest.raises(StaffMembershipForbidden):
        await reader.list_history(
            replace(actor, principal_kind=PrincipalKind.AGENT), ListStaffHistoryQuery(member)
        )
    assert _durable_counts(admin_conn) == before
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked',"
        "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='staff.read' AND status='active'",
        (actor.principal_id, actor.principal_id),
    )
    before = _durable_counts(admin_conn)
    with pytest.raises(StaffMembershipForbidden):
        await reader.list_history(actor, ListStaffHistoryQuery(member))
    assert _durable_counts(admin_conn) == before


@pytest.mark.asyncio
async def test_history_timestamp_ties_and_command_filter_bind_the_cursor(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    reader = PostgresStaffHistoryReader(command_session_factory)
    # These are realistic pre-existing audit facts for the READ projection, not
    # seeded outcomes claimed as evidence of a command. Equal timestamps expose
    # missing tie-breakers; mismatched audit kind/command exposes broad leakage.
    identifiers = [UUID(int=value) for value in (20, 10, 30, 40)]
    for identifier, kind, command in (
        (identifiers[0], "StaffMemberProfile", "staff.profile.update"),
        (identifiers[1], "StaffMemberProfile", "staff.profile.update"),
        (identifiers[2], "StaffMembership", "unrelated.private.command"),
        (identifiers[3], "UnrelatedAggregate", "staff.profile.update"),
    ):
        admin_conn.execute(
            "INSERT INTO request_engine.audit_records(id,organization_id,actor_principal_id,"
            "aggregate_kind,aggregate_id,command_name,created_at,details) "
            "VALUES(%s,%s,%s,%s,%s,%s,'2026-01-01T12:00:00Z',"
            '\'{"revision_before":"private-text","revision_after":-1,"token":"hidden"}\')',
            (identifier, actor.organization_id, actor.principal_id, kind, member, command),
        )
    newest_id = UUID(int=5)  # Later time must outrank a larger UUID.
    admin_conn.execute(
        "INSERT INTO request_engine.audit_records(id,organization_id,actor_principal_id,"
        "aggregate_kind,aggregate_id,command_name,created_at) "
        "VALUES(%s,%s,%s,'StaffMemberProfile',%s,'staff.profile.update','2026-01-02T12:00:00Z')",
        (newest_id, actor.organization_id, actor.principal_id, member),
    )
    first = await reader.list_history(actor, ListStaffHistoryQuery(member, limit=1))
    second = await reader.list_history(
        actor, ListStaffHistoryQuery(member, after=first.next_cursor, limit=2)
    )
    assert first.items[0].event_id == newest_id
    assert [item.event_id for item in second.items] == identifiers[:2]
    assert second.next_cursor is None
    assert all(
        item.revision_before is None and item.revision_after is None
        for item in first.items + second.items
    )
    for disallowed in identifiers[2:]:
        with pytest.raises(StaffMembershipInputInvalid):
            await reader.list_history(actor, ListStaffHistoryQuery(member, after=disallowed))


@pytest.mark.asyncio
async def test_history_http_executes_owner_reader_with_restricted_login(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    _, foreign_member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    await writer.update_staff_profile(
        actor,
        UpdateStaffProfileCommand(
            member,
            "Private name",
            0,
            "private:reason",
            uuid4().hex,
        ),
    )
    reader = PostgresStaffHistoryReader(command_session_factory)

    async def resolver(request: Request) -> ActorContext:
        # Authentication is excluded here; owner authority executes in PG through
        # a real non-superuser/NOBYPASSRLS LOGIN, not a mocked Session/reader.
        del request
        return actor

    app = FastAPI()
    router = APIRouter(prefix="/v1/staff")
    add_staff_history_reads(router, reader=reader, authenticated_actor=resolver)
    app.include_router(router)
    add_staff_membership_error_handlers(app)
    before = _durable_counts(admin_conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/staff/members/{member}/history")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        item = response.json()["items"][0]
        assert item["actor_principal_id"] == str(actor.principal_id)
        assert (item["command_name"], item["revision_before"], item["revision_after"]) == (
            "staff.profile.update",
            0,
            1,
        )
        assert "Private name" not in response.text and "private:reason" not in response.text
        foreign = await client.get(f"/v1/staff/members/{foreign_member}/history")
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "staff_membership_not_found"
        invalid = await client.get(
            f"/v1/staff/members/{member}/history", params={"after": str(uuid4())}
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "staff_membership_input_invalid"
    assert _durable_counts(admin_conn) == before
