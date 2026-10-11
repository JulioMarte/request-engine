"""Populated pre-binding upgrade, real crypto and restricted runtime login.

Defects caught: a native/setup handle mix-up, dropping credentials or authority,
retaining unsafe pending ceremonies/consent, and an unusable upgraded passkey.
Legacy rows are migration prerequisites, never the migration's expected result.
The unique database is intentionally separate from current-head data isolation.
"""

import hashlib
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_governance_support import provision_root, reset_actor, set_tenant_actor
from fido2 import cbor
from fido2.utils import websafe_decode
from fido2.webauthn import AttestationObject
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from software_webauthn_authenticator import SoftwareAuthenticator
from sqlalchemy.engine import URL

from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.db.webauthn_store import PostgresWebAuthnStore
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)
from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyError,
)
from request_engine.platform.security.webauthn import WebAuthnPolicy

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.provenance]
ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://localhost"
PgConnection = Connection[Any]


def _conninfo(database: str) -> str:
    return make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "request_engine"),
        password=os.environ.get("PGPASSWORD", "request_engine"),
        dbname=database,
        connect_timeout=5,
    )


def _url(
    database: str, *, driver: str = "psycopg", role: str | None = None, password: str | None = None
) -> str:
    config = conninfo_to_dict(_conninfo(database))
    return URL.create(
        f"postgresql+{driver}",
        username=role or str(config["user"]),
        password=password if password is not None else str(config["password"]),
        host=str(config["host"]),
        port=int(str(config["port"])),
        database=database,
    ).render_as_string(hide_password=False)


def _upgrade(database: str, revision: str) -> None:
    environment = {**os.environ, "MIGRATION_DATABASE_URL": _url(database)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
    )


@pytest.fixture
def legacy_database() -> Iterator[tuple[str, PgConnection]]:
    database = f"re_webauthn_upgrade_{uuid4().hex}"
    with psycopg.connect(_conninfo("postgres"), autocommit=True) as admin:
        assert int(admin.info.server_version) >= 180000
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            _upgrade(database, "0033_adopt_fact_tenant_rls")
            with psycopg.connect(_conninfo(database), autocommit=True) as connection:
                yield database, connection
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def _snapshot(conn: PgConnection, table: LiteralString) -> list[tuple[Any, ...]]:
    # These rows are independent authoritative preservation oracles. New columns
    # must not hide a changed old field; omit only explicitly added provenance.
    return conn.execute(
        sql.SQL(
            "SELECT to_jsonb(t) - 'user_handle' - 'controller_native_identity_id' "
            "- 'controller_recovery_epoch' FROM {} t ORDER BY 1"
        ).format(sql.Identifier("request_engine", table))
    ).fetchall()


def _legacy_passkey(
    conn: PgConnection,
    identity: UUID,
    *,
    setup_session: UUID | None = None,
) -> tuple[UUID, SoftwareAuthenticator]:
    authenticator = SoftwareAuthenticator(rp_id="localhost", origin=ORIGIN)
    # This represents the bytes sent to old authenticator firmware, independent
    # of migration helpers. A setup handle must NEVER become a native handle.
    source = (
        b"request-engine:native:" + identity.bytes
        if setup_session is None
        else b"request-engine:setup:" + setup_session.bytes
    )
    response = authenticator.registration_credential(
        challenge=secrets.token_bytes(32),
        user_handle=hashlib.sha256(source).digest(),
    )
    attestation = AttestationObject(websafe_decode(response["response"]["attestationObject"]))
    credential = attestation.auth_data.credential_data
    assert credential is not None
    public_key = cbor.encode(credential.public_key)
    credential_row = uuid4()
    conn.execute(
        "INSERT INTO request_engine.webauthn_credentials "
        "(id,native_identity_id,credential_id,public_key,aaguid) VALUES (%s,%s,%s,%s,%s)",
        (credential_row, identity, authenticator.credential_id, public_key, "00" * 16),
    )
    if setup_session is not None:
        conn.execute(
            "INSERT INTO request_engine.setup_pending_webauthn_credential "
            "(id,setup_session_id,credential_id,public_key,aaguid,status,promoted_at) "
            "VALUES (%s,%s,%s,%s,%s,'promoted',clock_timestamp())",
            (uuid4(), setup_session, authenticator.credential_id, public_key, "00" * 16),
        )
    return credential_row, authenticator


def _historical_applied_adoption(
    conn: PgConnection,
    *,
    approver_authority: UUID,
    approver_identity: UUID,
) -> None:
    """Produce the historical fact through the OLD commands, never insert it."""
    with conn.transaction():
        conn.execute(
            "SELECT request_platform.select_initial_controller_policy('tenant-controller-v1')"
        )
        organization, _party, controller, _authority = provision_root(conn)
    controller_row = conn.execute(
        "SELECT b.id,p.authority_revision FROM request_engine.identity_bindings b "
        "JOIN request_engine.principals p ON p.id=b.principal_id WHERE p.id=%s",
        (controller,),
    ).fetchone()
    assert controller_row is not None
    owner, owner_binding = uuid4(), uuid4()
    conn.execute(
        "INSERT INTO request_engine.principals "
        "(id,principal_plane,principal_kind,external_subject) VALUES (%s,'platform','human',%s)",
        (owner, f"historical-adoption-owner-{owner}"),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings "
        "(id,principal_id,principal_plane,identity_authority_id,subject_id,status) "
        "VALUES (%s,%s,'platform',%s,%s,'active')",
        (owner_binding, owner, approver_authority, str(approver_identity)),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants "
        "(principal_id,principal_plane,authority_plane,capability_key,delegable,"
        "provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','platform.organization.adopt_initial_controller_policy',"
        "false,'trust_bootstrap','historical-migration-world')",
        (owner,),
    )
    set_tenant_actor(conn, organization_id=organization, principal_id=controller)
    try:
        conn.execute(
            "SELECT set_config('request_engine.authority_revision',%s,false)",
            (str(controller_row[1]),),
        )
        requested = conn.execute(
            "SELECT request_id,request_revision FROM "
            "request_cmd.request_controller_policy_adoption(%s,%s,%s,%s,%s,%s)",
            (
                controller_row[0],
                controller_row[1],
                "Upgrade legacy permissions",
                "1" * 64,
                "2" * 64,
                uuid4(),
            ),
        ).fetchone()
        assert requested is not None
    finally:
        reset_actor(conn)
    owner_revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (owner,),
    ).fetchone()
    assert owner_revision is not None
    for name, value in (
        ("authenticated_principal_id", owner),
        ("identity_binding_id", owner_binding),
        ("authority_revision", owner_revision[0]),
        ("correlation_id", uuid4()),
    ):
        conn.execute("SELECT set_config(%s,%s,false)", (f"request_engine.{name}", str(value)))
    conn.execute("SET ROLE request_platform_control")
    try:
        applied = conn.execute(
            "SELECT fact_id FROM request_platform.apply_controller_policy_adoption(%s,%s,%s,%s)",
            (requested[0], requested[1], "3" * 64, "4" * 64),
        ).fetchone()
        assert applied is not None
    finally:
        reset_actor(conn)


@pytest.mark.asyncio
async def test_populated_upgrade_preserves_authority_and_both_legacy_passkey_sources(
    legacy_database: tuple[str, PgConnection],
) -> None:
    database, conn = legacy_database
    with conn.transaction():
        conn.execute(
            "SELECT request_platform.select_initial_controller_policy('tenant-controller-v1')"
        )
        org, _party, controller, authority = provision_root(conn)
    identity_row = conn.execute(
        "SELECT subject_id::uuid FROM request_engine.identity_bindings WHERE principal_id=%s",
        (controller,),
    ).fetchone()
    assert identity_row is not None
    identity = cast(UUID, identity_row[0])
    setup_session = uuid4()
    instance_row = conn.execute("SELECT id FROM request_engine.platform_instance").fetchone()
    assert instance_row is not None
    instance = cast(UUID, instance_row[0])
    conn.execute(
        "INSERT INTO request_engine.setup_sessions "
        "(id,instance_id,token_digest,token_fingerprint,mode,status,expires_at,consumed_at) "
        "VALUES (%s,%s,%s,%s,'interactive','consumed',clock_timestamp()+interval '1 hour',"
        "clock_timestamp())",
        (setup_session, instance, secrets.token_bytes(32), "0" * 16),
    )
    normal = _legacy_passkey(conn, identity)
    promoted = _legacy_passkey(conn, identity, setup_session=setup_session)
    pending_native, pending_setup, authentication, consumed = (uuid4() for _ in range(4))
    for challenge, purpose, status, native_id, setup_id in (
        (pending_native, "registration", "pending", identity, None),
        (pending_setup, "registration", "pending", None, setup_session),
        (authentication, "authentication", "pending", identity, None),
        (consumed, "registration", "consumed", identity, None),
    ):
        conn.execute(
            "INSERT INTO request_engine.webauthn_challenges "
            "(id,purpose,status,native_identity_id,setup_session_id,challenge_digest,"
            "expires_at,consumed_at) VALUES (%s,%s,%s,%s,%s,%s,"
            "clock_timestamp()+interval '1 hour',"
            "CASE WHEN %s='consumed' THEN clock_timestamp() END)",
            (challenge, purpose, status, native_id, setup_id, secrets.token_bytes(32), status),
        )
    conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked',"
        "revision=revision+1,revoked_at=clock_timestamp(),revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='staff.read'",
        (controller, controller),
    )
    pending_adoption = uuid4()
    binding_row = conn.execute(
        "SELECT id FROM request_engine.identity_bindings WHERE principal_id=%s",
        (controller,),
    ).fetchone()
    assert binding_row is not None
    binding = cast(UUID, binding_row[0])
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (controller,),
    ).fetchone()
    assert revision_row is not None
    conn.execute(
        "INSERT INTO request_engine.controller_policy_adoption_requests "
        "(id,organization_id,controller_principal_id,controller_binding_id,source_policy_key,"
        "target_policy_key,expected_authority_revision,reason,idempotency_key_digest,"
        "intent_digest,correlation_id,expires_at) "
        "VALUES (%s,%s,%s,%s,'tenant-controller-v1','tenant-controller-v6',%s,"
        "'Legacy pending consent',%s,%s,%s,clock_timestamp()+interval '1 hour')",
        (pending_adoption, org, controller, binding, revision_row[0], "a" * 64, "b" * 64, uuid4()),
    )
    withdrawn_adoption = uuid4()
    conn.execute(
        "INSERT INTO request_engine.controller_policy_adoption_requests "
        "(id,organization_id,controller_principal_id,controller_binding_id,source_policy_key,"
        "target_policy_key,expected_authority_revision,reason,idempotency_key_digest,"
        "intent_digest,correlation_id,expires_at,status,revision,closed_at,"
        "withdrawn_key_digest,withdrawn_intent_digest) "
        "VALUES (%s,%s,%s,%s,'tenant-controller-v1','tenant-controller-v6',%s,"
        "'Previously withdrawn consent',%s,%s,%s,clock_timestamp()+interval '1 hour',"
        "'withdrawn',2,clock_timestamp(),%s,%s)",
        (
            withdrawn_adoption,
            org,
            controller,
            binding,
            revision_row[0],
            "c" * 64,
            "d" * 64,
            uuid4(),
            "e" * 64,
            "f" * 64,
        ),
    )
    withdrawn_before = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.controller_policy_adoption_requests r WHERE id=%s",
        (withdrawn_adoption,),
    ).fetchone()
    _historical_applied_adoption(conn, approver_authority=authority, approver_identity=identity)
    applied_request_before = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.controller_policy_adoption_requests r "
        "WHERE status='applied'"
    ).fetchone()
    assert applied_request_before is not None
    preserved = (
        "native_identities",
        "identity_bindings",
        "principals",
        "principal_authority_grants",
        "organization_root_provisioning_facts",
        "webauthn_credentials",
        "setup_pending_webauthn_credential",
        "controller_policy_adoption_facts",
    )
    before = {table: _snapshot(conn, cast(LiteralString, table)) for table in preserved}
    _upgrade(database, "head")
    assert {table: _snapshot(conn, cast(LiteralString, table)) for table in preserved} == before
    assert conn.execute(
        "SELECT id,status FROM request_engine.webauthn_challenges ORDER BY id"
    ).fetchall() == sorted(
        [
            (pending_native, "expired"),
            (pending_setup, "expired"),
            (authentication, "pending"),
            (consumed, "consumed"),
        ]
    )
    assert conn.execute(
        "SELECT status,revision,closed_at IS NOT NULL,controller_native_identity_id,"
        "controller_recovery_epoch FROM request_engine.controller_policy_adoption_requests "
        "WHERE id=%s",
        (pending_adoption,),
    ).fetchone() == ("expired", 2, True, None, None)
    assert (
        conn.execute(
            "SELECT to_jsonb(r) - 'controller_native_identity_id' - 'controller_recovery_epoch' "
            "FROM request_engine.controller_policy_adoption_requests r WHERE id=%s",
            (withdrawn_adoption,),
        ).fetchone()
        == withdrawn_before
    )
    assert conn.execute(
        "SELECT count(*) FROM request_engine.controller_policy_adoption_facts"
    ).fetchone() == (1,)
    assert (
        conn.execute(
            "SELECT to_jsonb(r) - 'controller_native_identity_id' - 'controller_recovery_epoch' "
            "FROM request_engine.controller_policy_adoption_requests r WHERE status='applied'"
        ).fetchone()
        == applied_request_before
    )
    # Historic consent lacked a recovery snapshot. Migration must preserve it
    # as unknown rather than manufacture present-day evidence for a past act.
    assert conn.execute(
        "SELECT controller_native_identity_id,controller_recovery_epoch "
        "FROM request_engine.controller_policy_adoption_facts"
    ).fetchone() == (None, None)
    assert conn.execute(
        "SELECT credential_id,user_handle FROM request_engine.setup_pending_webauthn_credential"
    ).fetchone() == (promoted[1].credential_id, promoted[1].user_handle)
    for credential_row, authenticator in (normal, promoted):
        assert conn.execute(
            "SELECT user_handle FROM request_engine.webauthn_credentials WHERE id=%s",
            (credential_row,),
        ).fetchone() == (authenticator.user_handle,)
    # Repeated deploys must not regenerate handles or increment expiration again.
    upgraded_handles = conn.execute(
        "SELECT id,user_handle FROM request_engine.webauthn_credentials ORDER BY id"
    ).fetchall()
    _upgrade(database, "head")
    assert (
        conn.execute(
            "SELECT id,user_handle FROM request_engine.webauthn_credentials ORDER BY id"
        ).fetchall()
        == upgraded_handles
    )
    assert conn.execute(
        "SELECT status,revision FROM request_engine.controller_policy_adoption_requests "
        "WHERE id=%s",
        (pending_adoption,),
    ).fetchone() == ("expired", 2)

    role, password = f"re_upgrade_login_{uuid4().hex[:16]}", uuid4().hex
    conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS IN ROLE request_engine_app PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(password))
    )
    engine = create_postgres_engine(_url(database, driver="asyncpg", role=role, password=password))
    try:
        sessions = create_session_factory(engine)
        service = NativeWebAuthnAuthService(
            policy=WebAuthnPolicy(
                rp_id="localhost",
                rp_name="Upgrade proof",
                allowed_origins=frozenset({ORIGIN}),
                user_verification_required=True,
            ),
            store=PostgresWebAuthnStore(sessions),
        )
        # A genuine signature with a wrong user handle must still fail. This
        # catches a backfill that merely makes all passkeys accepted by id.
        options = await service.begin_authentication_discoverable()
        forged = promoted[1].authentication_credential(challenge=options.challenge)
        forged["response"]["userHandle"] = normal[1].authentication_credential(
            challenge=options.challenge
        )["response"]["userHandle"]
        with pytest.raises(WebAuthnCeremonyError, match="user_handle_mismatch"):
            await service.complete_discoverable_authentication(
                credential=forged,
                expected_authority_id=authority,
            )
        assert conn.execute("SELECT count(*) FROM request_engine.native_sessions").fetchone() == (
            0,
        )
        for credential_row, authenticator in (normal, promoted):
            options = await service.begin_authentication_discoverable()
            issued = await service.complete_discoverable_authentication(
                credential=authenticator.authentication_credential(challenge=options.challenge),
                expected_authority_id=authority,
            )
            evidence = await NativeSessionAuthenticator(
                session_reader=PostgresNativeSessionReader(sessions)
            ).authenticate(NativeSessionEvidence(issued.raw_token))
            assert evidence.subject_id == str(identity)
            assert conn.execute(
                "SELECT webauthn_credential_id,authentication_assurance,user_verified,"
                "recovery_derived FROM request_engine.native_sessions WHERE id=%s",
                (issued.session_id,),
            ).fetchone() == (credential_row, "phishing_resistant", True, False)
        assert conn.execute("SELECT count(*) FROM request_engine.native_sessions").fetchone() == (
            2,
        )
        assert _snapshot(conn, "principal_authority_grants") == before["principal_authority_grants"]
    finally:
        await engine.dispose()
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
