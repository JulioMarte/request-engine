import asyncio
from dataclasses import replace
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error
from test_staff_membership_lifecycle import (
    invite_active_staff,
    new_staff_native_identity,
    provision_staff_root,
)

from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_reader import (
    PostgresStaffMembershipReader,
)
from request_engine.modules.tenancy.application.commands.staff_membership import (
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
    UpdateStaffProfileCommand,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipConflict,
    StaffMembershipForbidden,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.context import ActorContext

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]


def _set_profile_actor(conn: Connection[Any], actor: ActorContext) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id',%s,false),"
        "set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(actor.organization_id), str(actor.principal_id)),
    )
    conn.execute("SET ROLE request_engine_app")


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
        capabilities=frozenset({"staff.manage_membership", "staff.read"}),
    ), member


def _command(member: UUID, name: str | None, revision: int = 0) -> UpdateStaffProfileCommand:
    return UpdateStaffProfileCommand(member, name, revision, "directory:review", uuid4().hex)


@pytest.mark.asyncio
async def test_profile_name_revision_replay_audit_and_authority_are_separate(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    reader = PostgresStaffMembershipReader(command_session_factory)
    before = await reader.read_membership(actor, member)
    assert (before.display_name, before.profile_revision) == (None, 0)
    command = _command(member, "  María Chen  ")
    assert await writer.update_staff_profile(actor, command) == 1
    assert await writer.update_staff_profile(actor, command) == 1
    named = await reader.read_membership(actor, member)
    assert (named.display_name, named.profile_revision) == ("María Chen", 1)
    assert (named.membership_revision, named.authority_revision, named.standing_grants) == (
        before.membership_revision,
        before.authority_revision,
        before.standing_grants,
    )
    with pytest.raises(IdempotencyConflict):
        await writer.update_staff_profile(actor, replace(command, display_name="Other"))
    with pytest.raises(StaffMembershipRevisionConflict):
        await writer.update_staff_profile(actor, _command(member, "Stale", 0))
    assert await writer.update_staff_profile(actor, _command(member, None, 1)) == 2
    assert await writer.update_staff_profile(actor, command) == 1
    cleared = await reader.read_membership(actor, member)
    assert (cleared.display_name, cleared.profile_revision) == (None, 2)
    audit = admin_conn.execute(
        "SELECT details FROM request_engine.audit_records "
        "WHERE aggregate_id=%s AND command_name='staff.profile.update' ORDER BY created_at",
        (member,),
    ).fetchall()
    assert len(audit) == 2
    assert [row[0]["revision_after"] for row in audit] == [1, 2]
    assert all("display_name" not in row[0] and "María" not in str(row[0]) for row in audit)


@pytest.mark.asyncio
async def test_profile_foreign_target_and_revoked_current_manager_fail_without_writes(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    foreign_actor, foreign_member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    with pytest.raises(StaffMembershipNotFound):
        await writer.update_staff_profile(actor, _command(foreign_member, "Foreign"))
    command = _command(member, "Manager approved")
    assert await writer.update_staff_profile(actor, command) == 1
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='staff.manage_membership' AND status='active'",
        (actor.principal_id, actor.principal_id),
    )
    with pytest.raises(StaffMembershipForbidden):
        await writer.update_staff_profile(actor, command)
    with pytest.raises(StaffMembershipForbidden):
        await writer.update_staff_profile(actor, _command(member, "Unauthorized", 1))
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_member_profiles WHERE organization_id=%s",
        (foreign_actor.organization_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT display_name,revision FROM request_engine.staff_member_profiles "
        "WHERE membership_id=%s",
        (member,),
    ).fetchone() == ("Manager approved", 1)


@pytest.mark.asyncio
async def test_profile_search_is_literal_tenant_scoped_and_applied_before_limit(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    foreign_actor, foreign_member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    reader = PostgresStaffMembershipReader(command_session_factory)
    await writer.update_staff_profile(actor, _command(member, "Álex 100%_match"))
    await writer.update_staff_profile(foreign_actor, _command(foreign_member, "Álex 100%_match"))
    for search in ("áLEX", "%_", "100%_match"):
        rows = await reader.list_memberships(
            actor, ListStaffMembershipsQuery(limit=1, search=search)
        )
        assert [row.membership_id for row in rows] == [member]
    assert await reader.list_memberships(actor, ListStaffMembershipsQuery(search="%anything")) == ()


def test_profile_table_runtime_dml_denied_and_foreign_rows_are_hidden(
    admin_conn: Connection[Any],
) -> None:
    actor, member = _world(admin_conn)
    foreign_actor, foreign_member = _world(admin_conn)
    _set_profile_actor(admin_conn, foreign_actor)
    try:
        admin_conn.execute(
            "SELECT request_cmd.write_staff_member_profile(%s,0,'Foreign','test')",
            (foreign_member,),
        )
    finally:
        admin_conn.execute("RESET ROLE")
    _set_profile_actor(admin_conn, actor)
    try:
        assert (
            admin_conn.execute(
                "SELECT membership_id,display_name FROM request_engine.staff_member_profiles"
            ).fetchall()
            == []
        )
        with pytest.raises(Error) as denied:
            admin_conn.execute(
                "INSERT INTO request_engine.staff_member_profiles "
                "(organization_id,membership_id,display_name,revision,updated_by_principal_id,"
                "provenance_reference) VALUES(%s,%s,'Bypass',1,%s,'test')",
                (actor.organization_id, member, actor.principal_id),
            )
        assert denied.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")


@pytest.mark.asyncio
async def test_revoked_member_profile_cannot_be_changed_or_replayed(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    actor, member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    reader = PostgresStaffMembershipReader(command_session_factory)
    command = _command(member, "Retained label")
    assert await writer.update_staff_profile(actor, command) == 1
    current = await reader.read_membership(actor, member)
    await writer.transition_staff_membership(
        actor,
        TransitionStaffMembershipCommand(
            member,
            current.membership_revision,
            StaffMembershipTargetStatus.REVOKED,
            "directory:revoke",
            uuid4().hex,
        ),
    )
    before = admin_conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.audit_records),"
        " (SELECT count(*) FROM request_engine.idempotency_records)"
    ).fetchone()
    for attempted in (command, _command(member, "Unauthorized rename", 1)):
        with pytest.raises(StaffMembershipConflict):
            await writer.update_staff_profile(actor, attempted)
    after = await reader.read_membership(actor, member)
    assert (after.status, after.display_name, after.profile_revision) == (
        "revoked",
        "Retained label",
        1,
    )
    assert (
        admin_conn.execute(
            "SELECT (SELECT count(*) FROM request_engine.audit_records),"
            " (SELECT count(*) FROM request_engine.idempotency_records)"
        ).fetchone()
        == before
    )


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_two_independent_profile_updates_have_one_stale_loser(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    pg_conninfo: str,
) -> None:
    actor, member = _world(admin_conn)
    writer = PostgresStaffMembershipCommands(command_session_factory)
    # Hold a real serialization row until BOTH independent sessions are waiting;
    # an event alone would only coordinate launch, not prove lock contention.
    holder = psycopg.connect(pg_conninfo)
    holder.execute(
        "SELECT id FROM request_engine.staff_memberships WHERE id=%s FOR UPDATE", (member,)
    )
    start = asyncio.Event()

    async def update(name: str) -> int:
        await start.wait()
        return await writer.update_staff_profile(actor, _command(member, name))

    first, second = asyncio.create_task(update("First")), asyncio.create_task(update("Second"))
    start.set()
    try:
        deadline = monotonic() + 10
        blocked = None
        while monotonic() < deadline:
            blocked = admin_conn.execute("""
                SELECT count(*) FROM pg_stat_activity
                 WHERE datname=current_database() AND wait_event_type='Lock'
                   AND query LIKE '%request_cmd.lock_staff_member_profile%'
            """).fetchone()
            if blocked == (2,):
                break
            await asyncio.sleep(0.01)
        assert blocked == (2,), "both profile commands must contend before the holder releases"
    finally:
        holder.rollback()
        holder.close()
        results = await asyncio.gather(first, second, return_exceptions=True)
    assert sum(result == 1 for result in results) == 1
    assert sum(isinstance(result, StaffMembershipRevisionConflict) for result in results) == 1
    assert admin_conn.execute(
        "SELECT revision FROM request_engine.staff_member_profiles WHERE membership_id=%s",
        (member,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE aggregate_id=%s AND command_name='staff.profile.update'",
        (member,),
    ).fetchone() == (1,)
