from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _platform_principal(conn: PgConnection, *, subject: str | None = None) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (subject or f"platform-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _platform_grant(
    conn: PgConnection,
    *,
    principal_id: UUID,
    capability: str,
    delegable: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (%s, 'platform', 'platform', %s, %s, 'trust_bootstrap', %s)
        """,
        (principal_id, capability, delegable, f"proof:{uuid4().hex}"),
    )


def _revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _set_platform_actor(conn: PgConnection, principal_id: UUID, revision: int) -> None:
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(revision),),
    )


def test_platform_controller_creates_bounded_tenant_provisioner(
    admin_conn: PgConnection,
) -> None:
    creator = _platform_principal(admin_conn)
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="platform.tenant_provisioner.provision",
        delegable=False,
    )
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="organization.provision",
        delegable=True,
    )
    revision = _revision(admin_conn, creator)
    provisioner = uuid4()

    _set_platform_actor(admin_conn, creator, revision)
    admin_conn.execute("SET ROLE request_engine_platform_control")
    try:
        row = admin_conn.execute(
            "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
            (provisioner, "native:tenant-provisioner-b", "proof:a-to-b"),
        ).fetchone()
    finally:
        admin_conn.execute("RESET ROLE")
    assert row == (provisioner,)

    principal = admin_conn.execute(
        """
        SELECT organization_id, principal_plane, principal_kind, active
          FROM request_engine.principals WHERE id = %s
        """,
        (provisioner,),
    ).fetchone()
    assert principal == (None, "platform", "human", True)

    grants = admin_conn.execute(
        """
        SELECT authority_plane, capability_key, delegable, granted_by_principal_id,
               provenance_kind
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active'
         ORDER BY capability_key
        """,
        (provisioner,),
    ).fetchall()
    assert grants == [
        ("platform", "organization.provision", False, creator, "provisioning")
    ]


def test_tenant_provisioner_requires_current_delegable_organization_authority(
    admin_conn: PgConnection,
) -> None:
    creator = _platform_principal(admin_conn)
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="platform.tenant_provisioner.provision",
        delegable=False,
    )
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="organization.provision",
        delegable=False,
    )
    _set_platform_actor(admin_conn, creator, _revision(admin_conn, creator))

    admin_conn.execute("SET ROLE request_engine_platform_control")
    try:
        with pytest.raises(Error) as rejected:
            admin_conn.execute(
                "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
                (uuid4(), "native:forbidden-b", "proof:no-delegability"),
            )
        assert rejected.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")


def test_stale_platform_authority_revision_cannot_provision(
    admin_conn: PgConnection,
) -> None:
    creator = _platform_principal(admin_conn)
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="platform.tenant_provisioner.provision",
        delegable=False,
    )
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="organization.provision",
        delegable=True,
    )
    stale_revision = _revision(admin_conn, creator)
    _platform_grant(
        admin_conn,
        principal_id=creator,
        capability="platform.principal.provision",
        delegable=False,
    )
    _set_platform_actor(admin_conn, creator, stale_revision)

    admin_conn.execute("SET ROLE request_engine_platform_control")
    try:
        with pytest.raises(Error) as rejected:
            admin_conn.execute(
                "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
                (uuid4(), "native:stale-b", "proof:stale"),
            )
        assert rejected.value.sqlstate == "40001"
    finally:
        admin_conn.execute("RESET ROLE")


def test_normal_app_role_cannot_execute_platform_provisioning(
    admin_conn: PgConnection,
) -> None:
    admin_conn.execute("SET ROLE request_engine_app")
    try:
        with pytest.raises(Error) as rejected:
            admin_conn.execute(
                "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
                (uuid4(), "native:forbidden", "proof:app-denied"),
            )
        assert rejected.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")
