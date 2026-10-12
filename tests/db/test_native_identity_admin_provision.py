import asyncio
import time
from dataclasses import asdict, replace
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from native_authority_gate_support import insert_authority
from platform_provisioning_support import platform_grant, platform_principal, principal_revision
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.native_identity_provision_commands import (
    PostgresNativeIdentityProvisionCommands,
)
from request_engine.modules.tenancy.adapters.db.native_identity_reader import (
    PostgresNativeIdentityReader,
)
from request_engine.modules.tenancy.adapters.db.platform_organization_reader import (
    PostgresPlatformOrganizationReader,
)
from request_engine.modules.tenancy.adapters.db.platform_owner_commands import (
    PostgresPlatformOwnerCommands,
)
from request_engine.modules.tenancy.adapters.db.platform_owner_reader import (
    PostgresPlatformOwnerReader,
)
from request_engine.modules.tenancy.api.platform_native_identity_management import (
    install_native_identity_management_http,
)
from request_engine.modules.tenancy.application.commands.native_identity_provision import (
    NativeIdentityProvisionConflict,
    NativeIdentityProvisionForbidden,
    ProvisionNativeIdentityCommand,
)
from request_engine.modules.tenancy.application.commands.platform_owner_lifecycle import (
    CreatePlatformOwnerInvitationCommand,
)
from request_engine.modules.tenancy.application.queries.native_identity_read import (
    GetNativeIdentityQuery,
    ListNativeIdentitiesQuery,
    NativeIdentityReadForbidden,
    NativeIdentityReadNotFound,
)
from request_engine.modules.tenancy.application.queries.platform_organization_read import (
    ListPlatformOrganizationsQuery,
)
from request_engine.modules.tenancy.application.queries.platform_owner_read import (
    PlatformOwnerReadForbidden,
    PlatformOwnerReadQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.native_auth import hash_password
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.platform_context import PlatformActorContext

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.adversarial,
    pytest.mark.invariant,
    pytest.mark.security,
]


def _world(
    conn: Connection[Any], *, passkey_only: bool = False
) -> tuple[Any, PlatformActorContext]:
    authority = insert_authority(conn)
    principal = platform_principal(conn)
    identity_id, credential_id = uuid4(), uuid4()
    conn.execute(
        "INSERT INTO request_engine.native_identities(id,identity_authority_id,login_handle) "
        "VALUES(%s,%s,%s)",
        (identity_id, authority, f"actor-{uuid4().hex}@example.test"),
    )
    if passkey_only:
        conn.execute(
            "INSERT INTO request_engine.webauthn_credentials("
            "id,native_identity_id,credential_id,public_key,aaguid) "
            "VALUES(%s,%s,%s,%s,%s)",
            (credential_id, identity_id, uuid4().bytes, b"accepted-public-key", "00" * 16),
        )
    else:
        conn.execute(
            "INSERT INTO request_engine.native_credentials(id,native_identity_id,verifier) "
            "VALUES(%s,%s,%s)",
            (credential_id, identity_id, hash_password("actor strong password")),
        )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES(%s,'platform',%s,%s,'active')",
        (principal, authority, str(identity_id)),
    )
    session_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.native_sessions(id,native_identity_id,"
        "password_credential_id,webauthn_credential_id,token_digest,token_fingerprint,"
        "session_epoch,expires_at,authentication_methods) "
        "VALUES(%s,%s,%s,%s,%s,%s,1,clock_timestamp()+interval '1 hour',%s)",
        (
            session_id,
            identity_id,
            None if passkey_only else credential_id,
            credential_id if passkey_only else None,
            b"s" * 32,
            uuid4().hex[:16],
            ["webauthn"] if passkey_only else ["password"],
        ),
    )
    for capability in (
        "platform.identity.provision",
        "platform.owner.read",
        "platform.owner.manage_lifecycle",
        "platform.owner.provision",
    ):
        platform_grant(conn, principal_id=principal, capability=capability, delegable=False)
    return authority, PlatformActorContext(
        principal_id=principal,
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset(
            {"platform.identity.provision", "platform.owner.read", "platform.owner.provision"}
        ),
        authority_revision=principal_revision(conn, principal),
        authentication_method="native_session",
        credential_id=str(session_id),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("passkey_only", [False, True])
async def test_admin_identity_retry_conflict_and_authority_withdrawal(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
    passkey_only: bool,
) -> None:
    authority, actor = _world(admin_conn, passkey_only=passkey_only)
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    command = ProvisionNativeIdentityCommand(
        f"admin-provision-{uuid4().hex}@example.test", "correct horse battery staple", "retry-key"
    )
    original = await commands.provision_identity(actor, command)
    replay = await commands.provision_identity(actor, command)
    assert replay == original
    with pytest.raises(NativeIdentityProvisionConflict):
        await commands.provision_identity(
            actor,
            ProvisionNativeIdentityCommand(
                command.login_handle, "a completely different password", command.idempotency_key
            ),
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities WHERE login_handle=%s",
        (command.login_handle,),
    ).fetchone() == (1,)

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_provision_receipts "
        "WHERE actor_principal_id=%s",
        (actor.principal_id,),
    ).fetchone() == (1,)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants "
        "SET status='revoked', revision=revision+1, revoked_at=clock_timestamp(), "
        "revoked_by_principal_id=principal_id "
        "WHERE principal_id=%s AND capability_key='platform.identity.provision'",
        (actor.principal_id,),
    )
    with pytest.raises(NativeIdentityProvisionForbidden):
        await commands.provision_identity(actor, command)


@pytest.mark.asyncio
@pytest.mark.parametrize("provenance", ["non_native", "missing_credential"])
async def test_native_provision_requires_explicit_native_credential_provenance(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
    provenance: str,
) -> None:
    authority, actor = _world(admin_conn)
    actor = (
        replace(actor, authentication_method="deployment_adapter")
        if provenance == "non_native"
        else replace(actor, credential_id=None)
    )
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    command = ProvisionNativeIdentityCommand(
        f"provenance-{uuid4().hex}@example.test", "accepted strong password", "provenance-proof"
    )
    with pytest.raises(NativeIdentityProvisionForbidden):
        await commands.provision_identity(actor, command)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities WHERE login_handle=%s",
        (command.login_handle,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_provision_receipts "
        "WHERE actor_principal_id=%s",
        (actor.principal_id,),
    ).fetchone() == (0,)


def _wait_for_actor_lock_waiters(admin: Connection[Any], holder_pid: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        count = admin.execute(
            "WITH RECURSIVE blocked(pid) AS ("
            " SELECT pid FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid))"
            " UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b"
            " ON b.pid=ANY(pg_blocking_pids(a.pid)))"
            " SELECT count(*) FROM pg_stat_activity WHERE pid IN (SELECT pid FROM blocked)"
            " AND query LIKE %s",
            (holder_pid, "%request_platform.provision_native_identity%"),
        ).fetchone()
        if count and count[0] >= 2:
            return
        time.sleep(0.01)
    raise AssertionError("Both independent provisioning sessions did not reach the actor lock")


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_admin_identity_retries_have_one_identity_and_receipt(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
) -> None:
    authority, actor = _world(admin_conn)
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    command = ProvisionNativeIdentityCommand(
        f"concurrent-{uuid4().hex}@example.test", "concurrent valid password", "same-operation"
    )
    # The lock makes the contested interleaving observable, not a timing guess.
    with psycopg.connect(admin_conn.info.dsn) as holder:
        holder.execute(
            "SELECT id FROM request_engine.principals WHERE id=%s FOR UPDATE", (actor.principal_id,)
        )
        attempts = [
            asyncio.create_task(commands.provision_identity(actor, command)) for _ in range(2)
        ]
        try:
            await asyncio.to_thread(
                _wait_for_actor_lock_waiters, admin_conn, holder.info.backend_pid
            )
        finally:
            holder.commit()
            results = await asyncio.gather(*attempts)
    assert results[0] == results[1]
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities WHERE login_handle=%s",
        (command.login_handle,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_provision_receipts "
        "WHERE actor_principal_id=%s",
        (actor.principal_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_owner_current_revision_and_pending_invitation_read_is_private(
    admin_conn: Connection[Any],
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority, actor = _world(admin_conn)
    reader = PostgresPlatformOwnerReader(platform_read_session_factory)
    owners = await reader.read_owners(actor, PlatformOwnerReadQuery(limit=1))
    assert len(owners) == 1 and owners[0].principal_id == actor.principal_id
    assert owners[0].authority_revision == actor.authority_revision
    assert await reader.read_invitations(actor, PlatformOwnerReadQuery()) == ()
    invitation = await PostgresPlatformOwnerCommands(
        platform_control_session_factory, native_authority_id=authority
    ).create_invitation(actor, CreatePlatformOwnerInvitationCommand("admin read proof", "invite"))
    rows = await reader.read_invitations(
        actor, PlatformOwnerReadQuery(resource_id=invitation.invitation_id)
    )
    assert len(rows) == 1 and rows[0].status == "pending" and rows[0].revision == 1
    assert rows[0].expires_at == invitation.expires_at and not rows[0].expired
    assert rows[0].native_identity_id is None and rows[0].enrolled_at is None
    admin_conn.execute(
        "UPDATE request_engine.principals SET active=false WHERE id=%s", (actor.principal_id,)
    )
    with pytest.raises(PlatformOwnerReadForbidden):
        await reader.read_owners(actor, PlatformOwnerReadQuery())


@pytest.mark.asyncio
@pytest.mark.parametrize("withdrawal", ["identity", "credential", "recovery", "binding"])
async def test_native_posture_withdrawal_denies_existing_provision_receipt(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
    withdrawal: str,
) -> None:
    authority, actor = _world(admin_conn)
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    command = ProvisionNativeIdentityCommand(
        f"posture-{uuid4().hex}@example.test", "accepted strong password", "posture-proof"
    )
    await commands.provision_identity(actor, command)
    row = admin_conn.execute(
        "SELECT native_identity_id FROM request_engine.native_sessions WHERE id=%s",
        (actor.credential_id,),
    ).fetchone()
    assert row is not None
    identity = UUID(str(row[0]))
    if withdrawal == "identity":
        admin_conn.execute(
            "UPDATE request_engine.native_identities SET status='disabled', "
            "revision=revision+1,session_epoch=session_epoch+1,"
            "disabled_at=clock_timestamp() WHERE id=%s",
            (identity,),
        )
    elif withdrawal == "credential":
        admin_conn.execute(
            "UPDATE request_engine.native_credentials SET status='revoked', "
            "revision=revision+1,revoked_at=clock_timestamp() WHERE id=("
            "SELECT password_credential_id FROM request_engine.native_sessions WHERE id=%s)",
            (actor.credential_id,),
        )
    elif withdrawal == "recovery":
        admin_conn.execute(
            "INSERT INTO request_engine.native_identity_recovery_state(native_identity_id,state, "
            "recovery_epoch,last_recovered_at,last_recovery_method) "
            "VALUES(%s,'recovery_restricted',1,clock_timestamp(),'recovery_code')",
            (identity,),
        )
    else:
        admin_conn.execute(
            "UPDATE request_engine.identity_bindings SET status='suspended', "
            "revision=revision+1 WHERE principal_id=%s",
            (actor.principal_id,),
        )
    # Principal and capability remain live: the rejected provenance is native authentication.
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id=%s", (actor.principal_id,)
    ).fetchone() == (True,)
    with pytest.raises(NativeIdentityProvisionForbidden):
        await commands.provision_identity(actor, command)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_provision_receipts "
        "WHERE actor_principal_id=%s",
        (actor.principal_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_maximum_directory_page_lookahead_uses_private_read_contract(
    admin_conn: Connection[Any],
    platform_read_session_factory: SessionFactory,
) -> None:
    _, actor = _world(admin_conn)
    actor = replace(actor, capabilities=actor.capabilities | {"platform.organization.read"})
    identities = sorted(uuid4() for _ in range(101))
    for identity in identities:
        admin_conn.execute(
            "INSERT INTO request_engine.organizations(id,organization_key,display_name) "
            "VALUES(%s,%s,'Lookahead proof')",
            (identity, f"lookahead-{identity.hex}"),
        )
    reader = PostgresPlatformOrganizationReader(platform_read_session_factory)
    rows = await reader.list_organizations(actor, ListPlatformOrganizationsQuery(limit=100))
    assert [row.organization_id for row in rows] == identities
    final = await reader.list_organizations(
        actor, ListPlatformOrganizationsQuery(after=identities[99], limit=100)
    )
    assert [row.organization_id for row in final] == identities[100:]


@pytest.mark.asyncio
@pytest.mark.parametrize("passkey_only", [False, True])
@pytest.mark.parametrize(
    "withdrawal", ["logout", "expired", "epoch", "credential_uuid", "recovery_derived"]
)
async def test_actual_session_provenance_is_required_before_provision_replay(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
    passkey_only: bool,
    withdrawal: str,
) -> None:
    authority, actor = _world(admin_conn, passkey_only=passkey_only)
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    command = ProvisionNativeIdentityCommand(
        f"session-{uuid4().hex}@example.test", "accepted session password", "session-proof"
    )
    await commands.provision_identity(actor, command)
    if withdrawal == "logout":
        row = admin_conn.execute(
            "SELECT native_identity_id FROM request_engine.native_sessions WHERE id=%s",
            (actor.credential_id,),
        ).fetchone()
        assert row is not None
        admin_conn.execute(
            "SELECT request_auth.revoke_native_session(%s,%s,'logout')",
            (row[0], actor.credential_id),
        )
    elif withdrawal == "epoch":
        row = admin_conn.execute(
            "SELECT native_identity_id FROM request_engine.native_sessions WHERE id=%s",
            (actor.credential_id,),
        ).fetchone()
        assert row is not None
        admin_conn.execute("SELECT request_auth.revoke_native_sessions(%s,'logout')", (row[0],))
        stale = uuid4()
        admin_conn.execute(
            "INSERT INTO request_engine.native_sessions(id,native_identity_id,"
            "password_credential_id,webauthn_credential_id,token_digest,token_fingerprint,"
            "session_epoch,expires_at,authentication_methods) "
            "SELECT %s,native_identity_id,password_credential_id,webauthn_credential_id,"
            "%s,%s,session_epoch,clock_timestamp()+interval '1 hour',authentication_methods "
            "FROM request_engine.native_sessions WHERE id=%s",
            (stale, b"t" * 32, uuid4().hex[:16], actor.credential_id),
        )
        actor = replace(actor, credential_id=str(stale))
    elif withdrawal == "credential_uuid":
        row = admin_conn.execute(
            "SELECT coalesce(password_credential_id,webauthn_credential_id) "
            "FROM request_engine.native_sessions WHERE id=%s",
            (actor.credential_id,),
        ).fetchone()
        assert row is not None
        actor = replace(actor, credential_id=str(row[0]))
    elif withdrawal == "recovery_derived":
        recovered = uuid4()
        admin_conn.execute(
            "INSERT INTO request_engine.native_sessions(id,native_identity_id,"
            "password_credential_id,webauthn_credential_id,token_digest,token_fingerprint,"
            "session_epoch,expires_at,authentication_methods,recovery_derived,"
            "authentication_assurance) "
            "SELECT %s,native_identity_id,password_credential_id,webauthn_credential_id,"
            "%s,%s,session_epoch,clock_timestamp()+interval '1 hour',"
            "authentication_methods || ARRAY['recovery_code'],'true','recovery' "
            "FROM request_engine.native_sessions WHERE id=%s",
            (recovered, b"r" * 32, uuid4().hex[:16], actor.credential_id),
        )
        actor = replace(actor, credential_id=str(recovered))
    else:
        expired = uuid4()
        admin_conn.execute(
            "INSERT INTO request_engine.native_sessions(id,native_identity_id,"
            "password_credential_id,webauthn_credential_id,token_digest,token_fingerprint,"
            "session_epoch,created_at,expires_at,authentication_methods) "
            "SELECT %s,native_identity_id,password_credential_id,webauthn_credential_id,"
            "%s,%s,session_epoch,clock_timestamp()-interval '2 hours',"
            "clock_timestamp()-interval '1 hour',authentication_methods "
            "FROM request_engine.native_sessions WHERE id=%s",
            (expired, b"e" * 32, uuid4().hex[:16], actor.credential_id),
        )
        actor = replace(actor, credential_id=str(expired))
    with pytest.raises(NativeIdentityProvisionForbidden):
        await commands.provision_identity(actor, command)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_provision_receipts "
        "WHERE actor_principal_id=%s",
        (actor.principal_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_native_identity_account_labels_are_private_exact_and_paginated(
    admin_conn: Connection[Any],
    platform_control_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
) -> None:
    authority, actor = _world(admin_conn)
    commands = PostgresNativeIdentityProvisionCommands(
        platform_control_session_factory, native_authority_id=authority
    )
    first_login = f"reception-{uuid4().hex}@example.test"
    second_login = f"manager-{uuid4().hex}@example.test"
    first = await commands.provision_identity(
        actor, ProvisionNativeIdentityCommand(first_login, "strong first password", "label-first")
    )
    second = await commands.provision_identity(
        actor,
        ProvisionNativeIdentityCommand(second_login, "strong second password", "label-second"),
    )
    reader = PostgresNativeIdentityReader(platform_read_session_factory)
    read_actor = replace(actor, capabilities=frozenset({"platform.identity.read"}))
    rows = await reader.list_identities(read_actor, ListNativeIdentitiesQuery())
    assert len(rows) == 3
    assert {row.native_identity_id: row.login_handle for row in rows}.items() >= {
        first.native_identity_id: first_login,
        second.native_identity_id: second_login,
    }.items()
    detail = await reader.read_identity(
        read_actor, GetNativeIdentityQuery(first.native_identity_id)
    )
    assert detail.login_handle == first_login
    assert detail.identity_authority_id == authority
    assert detail.revision == 1
    assert set(asdict(detail)) == {
        "native_identity_id",
        "identity_authority_id",
        "login_handle",
        "status",
        "revision",
        "created_at",
        "disabled_at",
    }
    observed: list[UUID] = []
    after = None
    while True:
        page = await reader.list_identities(read_actor, ListNativeIdentitiesQuery(after, 1))
        if not page:
            break
        observed.append(page[0].native_identity_id)
        after = page[0].native_identity_id
    assert observed == sorted(row.native_identity_id for row in rows)
    with pytest.raises(NativeIdentityReadNotFound):
        await reader.read_identity(read_actor, GetNativeIdentityQuery(uuid4()))
    for denied_actor in (
        replace(read_actor, capabilities=frozenset()),
        replace(read_actor, principal_kind=PrincipalKind.AGENT),
    ):
        with pytest.raises(NativeIdentityReadForbidden):
            await reader.list_identities(denied_actor, ListNativeIdentitiesQuery())
        with pytest.raises(NativeIdentityReadForbidden):
            await reader.read_identity(
                denied_actor, GetNativeIdentityQuery(first.native_identity_id)
            )
    async with platform_read_session_factory() as session:
        legacy = (
            await session.execute(
                text("SELECT * FROM request_platform.read_native_identities(NULL,NULL,100)")
            )
        ).all()
        assert all(len(row) == 6 for row in legacy)
        assert {row[0] for row in legacy} == set(observed)
    for forbidden_query in (
        "SELECT login_handle FROM request_engine.native_identities",
        "SELECT verifier FROM request_engine.native_credentials",
    ):
        async with platform_read_session_factory() as session:
            with pytest.raises(DBAPIError) as denied:
                await session.execute(text(forbidden_query))
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    assert admin_conn.execute(
        "SELECT has_function_privilege('public', "
        "'request_platform.read_native_identity_profiles(uuid,uuid,integer)', 'EXECUTE')"
    ).fetchone() == (False,)

    class ReadResolver:
        async def resolve_platform_actor(self, request: Request) -> PlatformActorContext:
            return read_actor

    app = FastAPI()
    install_native_identity_management_http(
        app,
        read_session_factory=platform_read_session_factory,
        write_session_factory=platform_control_session_factory,
        actor_resolver=ReadResolver(),
        native_auth_service=cast(NativeHumanAuthService, None),
        native_authority_id=authority,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get(f"/v1/platform/native-identities/{first.native_identity_id}")
        page_response = await client.get("/v1/platform/native-identities", params={"limit": 1})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["login_handle"] == first_login
    assert set(response.json()) == set(asdict(detail))
    assert page_response.status_code == 200
    assert page_response.headers["cache-control"] == "no-store"
    assert len(page_response.json()["items"]) == 1
    assert page_response.json()["next_cursor"] == str(observed[0])
    assert page_response.json()["items"][0]["login_handle"] == rows[0].login_handle
