import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


def uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def native_identity(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    authority_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"agent-native-{uuid4().hex}",),
    )
    identity_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.native_identities (
            identity_authority_id, login_handle
        ) VALUES (%s, %s) RETURNING id
        """,
        (authority_id, f"agent-root-{uuid4().hex}@example.test"),
    )
    credential_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.native_credentials (
            native_identity_id, verifier
        ) VALUES (%s, %s) RETURNING id
        """,
        (identity_id, "scrypt$" + ("x" * 64)),
    )
    return authority_id, identity_id, credential_id


def principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def provision_root(
    conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID]:
    provisioner_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"agent-platform-{uuid4().hex}",),
    )
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (
            %s, 'platform', 'platform', 'organization.provision', false,
            'trust_bootstrap', %s
        )
        """,
        (provisioner_id, f"agent-root:{uuid4().hex}"),
    )
    authority_id, native_identity_id, _credential_id = native_identity(conn)
    organization_id = uuid4()
    party_id = uuid4()
    controller_id = uuid4()

    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(conn, provisioner_id)),),
    )
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"agent-tenant-{organization_id.hex}",
                "Agent Governance Tenant",
                party_id,
                controller_id,
                authority_id,
                native_identity_id,
                f"agent-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, party_id, controller_id, authority_id


def set_tenant_actor(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    conn.execute("SET ROLE request_engine_app")


def reset_actor(conn: PgConnection) -> None:
    conn.execute("RESET ROLE")
    conn.execute("SELECT set_config('request_engine.organization_id', '', false)")
    conn.execute("SELECT set_config('request_engine.authenticated_principal_id', '', false)")


def workload_authority(conn: PgConnection) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('workload', %s) RETURNING id
        """,
        (f"agent-workload-{uuid4().hex}",),
    )


def issue_agent_secret() -> tuple[bytes, str]:
    secret = secrets.token_urlsafe(32)
    return hashlib.sha256(secret.encode("utf-8")).digest(), secret


def provision_agent(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    workload_authority_id: UUID,
    sponsor_principal_id: UUID | None = None,
    display_name: str = "Clinic Scheduling Agent",
) -> tuple[UUID, UUID, UUID, UUID, str]:
    digest, secret = issue_agent_secret()
    agent_principal_id = uuid4()
    binding_id = uuid4()
    workload_identity_id = uuid4()
    credential_id = uuid4()
    set_tenant_actor(
        conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        revision = conn.execute(
            """
            SELECT request_engine.provision_agent(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'autonomous', %s
            )
            """,
            (
                agent_principal_id,
                binding_id,
                workload_identity_id,
                credential_id,
                workload_authority_id,
                digest,
                digest.hex()[:16],
                datetime.now(UTC) + timedelta(days=30),
                display_name,
                "book appointments for patients",
                sponsor_principal_id or controller_id,
                f"agent-provision:{uuid4().hex}",
            ),
        ).fetchone()
        assert revision is not None and int(revision[0]) == 1
    finally:
        reset_actor(conn)
    token = f"{credential_id}.{secret}"
    return agent_principal_id, binding_id, workload_identity_id, credential_id, token


def grant_delegable(
    conn: PgConnection,
    *,
    principal_id: UUID,
    organization_id: UUID,
    capability_key: str,
    authority_plane: str,
) -> None:
    revoked = conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked',
               revision = revision + 1,
               revoked_at = clock_timestamp(),
               revoked_by_principal_id = %s
         WHERE principal_id = %s
           AND organization_id = %s
           AND capability_key = %s
           AND authority_plane = %s
           AND status = 'active'
        """,
        (principal_id, principal_id, organization_id, capability_key, authority_plane),
    ).rowcount
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', %s, %s, true, %s, 'authority_management', %s
        )
        """,
        (
            organization_id,
            principal_id,
            authority_plane,
            capability_key,
            principal_id,
            f"grant:{uuid4().hex}",
        ),
    )
    assert revoked >= 0


def transition_agent(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    agent_principal_id: UUID,
    expected_revision: int,
    target_status: str,
) -> int:
    set_tenant_actor(
        conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        row = conn.execute(
            """
            SELECT request_engine.transition_agent_profile(%s, %s, %s, %s)
            """,
            (
                agent_principal_id,
                expected_revision,
                target_status,
                f"agent-transition:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        reset_actor(conn)
