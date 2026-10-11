"""Current-authority receipts: restricted-runtime regressions and lock races."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection
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
    InviteNativeStaffCommand,
    InviteNativeStaffResult,
    ReplaceStaffAuthorityCommand,
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
)
from request_engine.modules.tenancy.application.errors import StaffMembershipForbidden
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [pytest.mark.postgres, pytest.mark.adversarial, pytest.mark.security]


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("winner", ["revocation", "replay"])
@pytest.mark.parametrize(
    "capability", ["staff.invite", "staff.manage_authority", "staff.manage_membership"]
)
async def test_completed_staff_replay_revalidates_current_actor_grant(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    capability: str,
    app_role_conn_factory: Callable[[], Connection[Any]],
    winner: str,
) -> None:
    organization, party, root_id, _, _ = provision_staff_root(admin_conn)
    target_authority, target_identity, _ = new_staff_native_identity(admin_conn)
    target, _, _ = invite_active_staff(
        admin_conn,
        organization_id=organization,
        root_id=root_id,
        party_id=party,
        authority_id=target_authority,
        native_identity_id=target_identity,
    )
    root = ActorContext(
        organization_id=organization,
        principal_id=root_id,
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset(
            {"staff.read", "staff.invite", "staff.manage_authority", "staff.manage_membership"}
        ),
    )
    row = admin_conn.execute(
        "SELECT authority_anchor_party_id FROM request_engine.staff_memberships "
        "WHERE principal_id=%s",
        (root.principal_id,),
    ).fetchone()
    assert row is not None
    authority, identity, _ = new_staff_native_identity(admin_conn)
    member, principal, _ = invite_active_staff(
        admin_conn,
        organization_id=root.organization_id,
        root_id=root.principal_id,
        party_id=row[0],
        authority_id=authority,
        native_identity_id=identity,
    )
    writer = PostgresStaffMembershipCommands(command_session_factory)
    reader = PostgresStaffMembershipReader(command_session_factory)
    current = await reader.read_membership(root, member)
    await writer.replace_staff_authority(
        root,
        ReplaceStaffAuthorityCommand(
            member, current.authority_revision, (capability,), "probe:grant", uuid4().hex
        ),
    )
    stale = replace(root, principal_id=principal, capabilities=frozenset({capability}))
    target_before = await reader.read_membership(root, target)
    command: (
        InviteNativeStaffCommand | ReplaceStaffAuthorityCommand | TransitionStaffMembershipCommand
    )

    async def operation(
        actor: ActorContext,
        value: InviteNativeStaffCommand
        | ReplaceStaffAuthorityCommand
        | TransitionStaffMembershipCommand,
    ) -> InviteNativeStaffResult | int:
        if isinstance(value, InviteNativeStaffCommand):
            return await writer.invite_native_staff(actor, value)
        if isinstance(value, ReplaceStaffAuthorityCommand):
            return await writer.replace_staff_authority(actor, value)
        return await writer.transition_staff_membership(actor, value)

    if capability == "staff.invite":
        fresh_authority, fresh_identity, _ = new_staff_native_identity(admin_conn)
        command = InviteNativeStaffCommand(
            fresh_authority, fresh_identity, "probe:invite", uuid4().hex
        )
    elif capability == "staff.manage_authority":
        command = ReplaceStaffAuthorityCommand(
            target, target_before.authority_revision, (), "probe:replace", uuid4().hex
        )
    else:
        command = TransitionStaffMembershipCommand(
            target,
            target_before.membership_revision,
            StaffMembershipTargetStatus.SUSPENDED,
            "probe:suspend",
            uuid4().hex,
        )
    original = await operation(stale, command)
    assert original is not None
    with pytest.raises(StaffMembershipForbidden):
        await operation(replace(stale, capabilities=frozenset()), command)
    # Another authorized command advances the target after the original result.
    # Receipt replay must not run target CAS again or repeat any mutation.
    if capability == "staff.manage_authority":
        assert isinstance(original, int)
        await writer.replace_staff_authority(
            root,
            ReplaceStaffAuthorityCommand(target, original, (), "proof:advance", uuid4().hex),
        )
    elif capability == "staff.manage_membership":
        assert isinstance(original, int)
        await writer.transition_staff_membership(
            root,
            TransitionStaffMembershipCommand(
                target, original, StaffMembershipTargetStatus.ACTIVE, "proof:advance", uuid4().hex
            ),
        )
    before_replay = admin_conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.audit_records),"
        " (SELECT count(*) FROM request_engine.idempotency_records),"
        " (SELECT sum(authority_revision) FROM request_engine.principals),"
        " (SELECT sum(revision) FROM request_engine.staff_memberships)"
    ).fetchone()
    assert await operation(stale, command) == original
    assert (
        admin_conn.execute(
            "SELECT (SELECT count(*) FROM request_engine.audit_records),"
            " (SELECT count(*) FROM request_engine.idempotency_records),"
            " (SELECT sum(authority_revision) FROM request_engine.principals),"
            " (SELECT sum(revision) FROM request_engine.staff_memberships)"
        ).fetchone()
        == before_replay
    )
    actor_current = await reader.read_membership(root, member)
    holder, contender = app_role_conn_factory(), app_role_conn_factory()
    for conn, context in ((holder, root if winner == "revocation" else stale), (contender, root)):
        _context(conn, context)
        conn.execute("SET LOCAL statement_timeout='12s'")
    revoke_sql = "SELECT request_engine.replace_staff_authority(%s,%s,ARRAY[]::text[],%s)"
    revoke_args = (member, actor_current.authority_revision, "proof:concurrent-withdraw")
    if winner == "revocation":
        holder.execute(revoke_sql, revoke_args)
        attempt = asyncio.create_task(operation(stale, command))
        try:
            await _wait_blocked(admin_conn, holder.info.backend_pid)
        finally:
            holder.commit()
        with pytest.raises(StaffMembershipForbidden):
            await attempt
    else:
        persisted = admin_conn.execute(
            "SELECT request_fingerprint FROM request_engine.idempotency_records "
            "WHERE principal_id=%s AND capability=%s AND idempotency_key=%s",
            (principal, capability, command.idempotency_key),
        ).fetchone()
        assert persisted is not None
        receipt = holder.execute(
            "SELECT * FROM request_cmd.acquire_idempotency(%s,%s,%s,%s,%s)",
            (root.organization_id, principal, capability, command.idempotency_key, persisted[0]),
        ).fetchone()
        assert receipt is not None
        assert holder.execute(
            "SELECT request_cmd.lock_staff_command_authority(%s)", (capability,)
        ).fetchone() == (principal,)
        with ThreadPoolExecutor(max_workers=1) as executor:
            withdrawal = executor.submit(contender.execute, revoke_sql, revoke_args)
            try:
                await _wait_blocked(admin_conn, holder.info.backend_pid)
                assert receipt[-1] is True, "completed receipt recovered under current locks"
            finally:
                holder.commit()
            withdrawal.result(timeout=15)
            contender.commit()
    assert capability not in {
        grant.capability for grant in (await reader.read_membership(root, member)).standing_grants
    }
    before = admin_conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.audit_records),"
        " (SELECT count(*) FROM request_engine.idempotency_records),"
        " (SELECT count(*) FROM request_engine.staff_memberships),"
        " (SELECT sum(authority_revision) FROM request_engine.principals),"
        " (SELECT sum(revision) FROM request_engine.staff_memberships)"
    ).fetchone()
    with pytest.raises(StaffMembershipForbidden):
        await operation(stale, command)
    assert (
        admin_conn.execute(
            "SELECT (SELECT count(*) FROM request_engine.audit_records),"
            " (SELECT count(*) FROM request_engine.idempotency_records),"
            " (SELECT count(*) FROM request_engine.staff_memberships),"
            " (SELECT sum(authority_revision) FROM request_engine.principals),"
            " (SELECT sum(revision) FROM request_engine.staff_memberships)"
        ).fetchone()
        == before
    )
    with pytest.raises(StaffMembershipForbidden):
        await operation(stale, replace(command, idempotency_key=uuid4().hex))
    holder.close()
    contender.close()


def _context(conn: Connection[Any], actor: ActorContext) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id',%s,true),"
        "set_config('request_engine.authenticated_principal_id',%s,true)",
        (str(actor.organization_id), str(actor.principal_id)),
    )


async def _wait_blocked(conn: Connection[Any], holder_pid: int) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        row = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
            "AND wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid))",
            (holder_pid,),
        ).fetchone()
        if row == (1,):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("independent authoritative transaction did not contend")
