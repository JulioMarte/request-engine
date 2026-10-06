"""Adversarial apply/apply idempotency and serialization proofs on PostgreSQL."""

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ApplyControllerPolicyAdoption,
    ControllerPolicyAdoptionConflict,
    ControllerPolicyAdoptionResult,
    RequestControllerPolicyAdoption,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.postgres import command_fingerprint
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.concurrency,
]


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def _create_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"adoption-apply-race-{uuid4().hex}",),
    )


def _provision_root(
    conn: PgConnection, authority_id: UUID, native_id: UUID
) -> tuple[UUID, UUID, UUID]:
    provisioner = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"adoption-apply-race-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner, f"apply-race-provisioner:{uuid4().hex}"),
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (provisioner,)
    ).fetchone()
    assert revision_row is not None
    revision = int(revision_row[0])
    organization_id, party_id, root_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)", (str(revision),)
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute(
                "SELECT request_platform.select_initial_controller_policy(%s)",
                ("tenant-controller-v1",),
            )
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"apply-race-{organization_id.hex}",
                    "Adoption apply race proof",
                    party_id,
                    root_id,
                    authority_id,
                    native_id,
                    f"apply-race-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    binding_id = _uuid_row(
        conn,
        "SELECT controller_binding_id FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (organization_id,),
    )
    return organization_id, root_id, binding_id


def _platform_actor(
    conn: PgConnection, authority_id: UUID, native_id: UUID
) -> PlatformActorContext:
    principal = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"adoption-apply-race-owner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES (%s,'platform',%s,%s,'active')",
        (principal, authority_id, str(native_id)),
    )
    for capability in (
        "platform.organization.adopt_initial_controller_policy",
        "platform.organization.read",
    ):
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,provenance_kind,"
            "provenance_reference) VALUES (%s,'platform','platform',%s,false,"
            "'trust_bootstrap',%s)",
            (principal, capability, f"apply-race-owner:{uuid4().hex}"),
        )
    binding = _uuid_row(
        conn, "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s", (principal,)
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (principal,)
    ).fetchone()
    assert revision_row is not None
    revision = int(revision_row[0])
    return PlatformActorContext(
        principal_id=principal,
        capabilities=frozenset(
            {
                "platform.organization.adopt_initial_controller_policy",
                "platform.organization.read",
            }
        ),
        authority_revision=revision,
        identity_binding_id=binding,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=datetime.now(UTC),
    )


def _root_actor(
    conn: PgConnection, organization_id: UUID, root_id: UUID, binding_id: UUID
) -> ActorContext:
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (root_id,)
    ).fetchone()
    assert revision_row is not None
    revision = int(revision_row[0])
    capabilities = frozenset(
        str(row[0])
        for row in conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s AND status='active'",
            (organization_id, root_id),
        ).fetchall()
    )
    return ActorContext(
        organization_id=organization_id,
        principal_id=root_id,
        capabilities=capabilities,
        authority_revision=revision,
        identity_binding_id=binding_id,
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=datetime.now(UTC),
    )


async def _wait_for_blocker(observer: PgConnection, query_fragment: str, blocker_pid: int) -> int:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        rows = observer.execute(
            "SELECT pid,pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE %s",
            (f"%{query_fragment}%",),
        ).fetchall()
        for pid, blockers in rows:
            if blocker_pid in blockers:
                return int(pid)
        await asyncio.sleep(0.025)
    raise AssertionError(
        f"PostgreSQL did not report {query_fragment!r} blocked by backend {blocker_pid}"
    )


@pytest.mark.parametrize(
    ("retry_same_key_and_payload",),
    ((True,), (False,)),
    ids=("same-key-same-payload-replays", "different-key-payload-conflicts"),
)
@pytest.mark.asyncio
async def test_concurrent_apply_serializes_replay_or_conflict_without_duplicate_effects(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    retry_same_key_and_payload: bool,
) -> None:
    """Same-key retry replays; another key/payload conflicts after waiting for the winner."""
    authority_id = _create_authority(e2e_admin_conn)
    enrollment = build_native_auth_runtime(e2e_session_factory)
    root_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"apply-race-root-{uuid4().hex}@example.test",
        password="apply-race-root-password-1",
    )
    platform_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"apply-race-owner-{uuid4().hex}@example.test",
        password="apply-race-owner-password-2",
    )
    organization_id, root_id, root_binding_id = _provision_root(
        e2e_admin_conn, authority_id, root_identity.native_identity_id
    )
    root_actor = _root_actor(e2e_admin_conn, organization_id, root_id, root_binding_id)
    assert root_actor.authority_revision is not None
    platform_actor = _platform_actor(
        e2e_admin_conn, authority_id, platform_identity.native_identity_id
    )
    commands = PostgresControllerPolicyAdoptionCommands(
        e2e_session_factory, platform_session_factory=platform_control_session_factory
    )
    request = await commands.request_adoption(
        root_actor,
        RequestControllerPolicyAdoption(
            expected_authority_revision=root_actor.authority_revision,
            reason="Apply the same approved policy exactly once",
            idempotency_key=f"apply-race-request:{uuid4().hex}",
        ),
    )

    retry_key = f"same-retry:{uuid4().hex}"
    retry_revision = (
        request.request_revision if retry_same_key_and_payload else (request.request_revision + 1)
    )
    retry_effective_key = retry_key if retry_same_key_and_payload else f"different:{retry_key}"
    key_digest = hashlib.sha256(retry_key.encode("utf-8")).hexdigest()
    intent_digest = command_fingerprint(
        "platform.organization.adopt_initial_controller_policy",
        {
            "request_id": request.request_id,
            "expected_request_revision": request.request_revision,
        },
    )
    for setting, value in (
        ("request_engine.authenticated_principal_id", str(platform_actor.principal_id)),
        ("request_engine.authority_revision", str(platform_actor.authority_revision)),
        ("request_engine.identity_binding_id", str(platform_actor.identity_binding_id)),
        ("request_engine.correlation_id", str(uuid4())),
    ):
        e2e_barrier_conn.execute("SELECT set_config(%s,%s,false)", (setting, value))

    first_fact_id: UUID | None = None
    retry_task: asyncio.Task[ControllerPolicyAdoptionResult] | None = None
    try:
        e2e_barrier_conn.execute("SET LOCAL ROLE request_platform_control")
        first = e2e_barrier_conn.execute(
            "SELECT * FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
            (request.request_id, request.request_revision, key_digest, intent_digest),
        ).fetchone()
        assert first is not None
        first_fact_id = first[0]
        first_pid = e2e_barrier_conn.info.backend_pid
        retry_task = asyncio.create_task(
            commands.apply_adoption(
                platform_actor,
                ApplyControllerPolicyAdoption(
                    request_id=request.request_id,
                    expected_request_revision=retry_revision,
                    idempotency_key=retry_effective_key,
                ),
            )
        )
        await _wait_for_blocker(
            e2e_admin_conn,
            "apply_controller_policy_adoption",
            first_pid,
        )
        e2e_barrier_conn.commit()
        if retry_same_key_and_payload:
            retry_result = await asyncio.wait_for(retry_task, timeout=15)
        else:
            with pytest.raises(ControllerPolicyAdoptionConflict):
                await asyncio.wait_for(retry_task, timeout=15)
            retry_result = None
    finally:
        if not e2e_barrier_conn.autocommit:
            e2e_barrier_conn.rollback()
        for setting in (
            "request_engine.authenticated_principal_id",
            "request_engine.authority_revision",
            "request_engine.identity_binding_id",
            "request_engine.correlation_id",
        ):
            e2e_barrier_conn.execute("SELECT set_config(%s,'',false)", (setting,))
        e2e_barrier_conn.commit()
        if retry_task is not None and not retry_task.done():
            retry_task.cancel()
            await asyncio.gather(retry_task, return_exceptions=True)

    assert first_fact_id is not None
    if retry_same_key_and_payload:
        assert retry_result is not None
        assert retry_result.fact_id == first_fact_id
        assert retry_result.request_id == request.request_id
    state = e2e_admin_conn.execute(
        "SELECT status,revision FROM request_engine.controller_policy_adoption_requests "
        "WHERE id=%s",
        (request.request_id,),
    ).fetchone()
    assert state == ("applied", request.request_revision + 1)
    facts = e2e_admin_conn.execute(
        "SELECT id,added_capabilities,idempotency_key_digest,intent_digest "
        "FROM request_engine.controller_policy_adoption_facts WHERE request_id=%s",
        (request.request_id,),
    ).fetchall()
    assert len(facts) == 1
    assert facts[0][0] == first_fact_id
    assert facts[0][2:] == (key_digest, intent_digest)
    added = set(facts[0][1])
    grants = {
        str(row[0])
        for row in e2e_admin_conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s AND principal_id=%s "
            "AND provenance_reference=%s AND status='active'",
            (organization_id, root_id, f"adoption:{request.request_id}"),
        ).fetchall()
    }
    assert grants == added
