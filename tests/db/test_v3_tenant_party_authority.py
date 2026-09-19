from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"authority-{suffix}", f"Authority {suffix}"),
    )


def _principal(conn: PgConnection, organization_id: UUID | None) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_plane, principal_kind, external_subject
        ) VALUES (%s, %s, 'human', %s)
        RETURNING id
        """,
        (
            organization_id,
            "platform" if organization_id is None else "tenant",
            f"principal-{uuid4().hex}",
        ),
    )


def _party(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Party {uuid4().hex}"),
    )


def _binding(conn: PgConnection, organization_id: UUID | None, principal_id: UUID) -> UUID:
    authority_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment) "
        "VALUES ('oidc', %s) RETURNING id",
        (f"https://identity-{uuid4().hex}.example.test",),
    )
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.identity_bindings "
        "(organization_id, principal_plane, principal_id, identity_authority_id, "
        "subject_id, status) "
        "VALUES (%s, %s, %s, %s, %s, 'active') RETURNING id",
        (
            organization_id,
            "platform" if organization_id is None else "tenant",
            principal_id,
            authority_id,
            uuid4().hex,
        ),
    )


def _grant(
    conn: PgConnection,
    organization_id: UUID | None,
    principal_id: UUID,
    grantor: UUID | None,
) -> UUID:
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.principal_authority_grants "
        "(organization_id, principal_plane, principal_id, authority_plane, capability_key, "
        "granted_by_principal_id, provenance_kind, provenance_reference) "
        "VALUES (%s, %s, %s, %s, 'staff.manage_membership', %s, %s, %s) RETURNING id",
        (
            organization_id,
            "platform" if organization_id is None else "tenant",
            principal_id,
            "platform" if organization_id is None else "tenant_control",
            grantor,
            "trust_bootstrap" if grantor is None else "provisioning",
            uuid4().hex,
        ),
    )


@pytest.mark.parametrize("action", ["grant", "revoke"])
def test_grant_provenance_rejects_foreign_tenant_and_preserves_revision(
    admin_conn: PgConnection,
    action: str,
) -> None:
    org = _organization(admin_conn)
    target = _principal(admin_conn, org)
    foreign = _principal(admin_conn, _organization(admin_conn))
    grant_id = (
        _grant(admin_conn, org, target, _principal(admin_conn, org)) if action == "revoke" else None
    )
    before = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (target,),
    ).fetchone()
    with pytest.raises(Error) as error, admin_conn.transaction():
        if grant_id is None:
            _grant(admin_conn, org, target, foreign)
        else:
            admin_conn.execute(
                "UPDATE request_engine.principal_authority_grants SET status = 'revoked', "
                "revision = revision + 1, revoked_at = clock_timestamp(), "
                "revoked_by_principal_id = %s WHERE id = %s",
                (foreign, grant_id),
            )
    assert error.value.sqlstate == "23514"
    assert (
        admin_conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
            (target,),
        ).fetchone()
        == before
    )
    assert admin_conn.execute(
        "SELECT status, revision, revoked_by_principal_id "
        "FROM request_engine.principal_authority_grants WHERE principal_id = %s",
        (target,),
    ).fetchall() == ([] if grant_id is None else [("active", 1, None)])


def test_platform_identity_and_provisioning_provenance_remain_valid(
    admin_conn: PgConnection,
) -> None:
    org = _organization(admin_conn)
    platform = _principal(admin_conn, None)
    tenant = _principal(admin_conn, org)
    binding = _binding(admin_conn, None, platform)
    _grant(admin_conn, None, platform, None)
    tenant_grant = _grant(admin_conn, org, tenant, platform)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status = 'revoked', "
        "revision = revision + 1, revoked_at = clock_timestamp(), "
        "revoked_by_principal_id = %s WHERE id = %s",
        (platform, tenant_grant),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.organization_provisioning_facts "
        "(organization_id, provisioned_by_principal_id, provenance_reference) VALUES (%s, %s, %s)",
        (org, platform, uuid4().hex),
    )
    assert admin_conn.execute(
        "SELECT organization_id, principal_id FROM request_engine.identity_bindings WHERE id = %s",
        (binding,),
    ).fetchone() == (None, platform)
    assert admin_conn.execute(
        "SELECT status, revoked_by_principal_id FROM request_engine.principal_authority_grants "
        "WHERE id = %s",
        (tenant_grant,),
    ).fetchone() == ("revoked", platform)
    assert admin_conn.execute(
        "SELECT principal_plane, organization_id FROM request_engine.principals WHERE id = %s",
        (platform,),
    ).fetchone() == ("platform", None)


@pytest.mark.parametrize("foreign", [False, True])
def test_organization_provenance_requires_platform_principal(
    admin_conn: PgConnection,
    foreign: bool,
) -> None:
    org = _organization(admin_conn)
    actor = _principal(admin_conn, _organization(admin_conn) if foreign else org)
    with pytest.raises(Error) as error, admin_conn.transaction():
        admin_conn.execute(
            "INSERT INTO request_engine.organization_provisioning_facts "
            "(organization_id, provisioned_by_principal_id, provenance_reference) "
            "VALUES (%s, %s, %s)",
            (org, actor, uuid4().hex),
        )
    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.organization_provisioning_facts "
        "WHERE organization_id = %s",
        (org,),
    ).fetchone() == (0,)


@pytest.mark.parametrize("provenance", ["root_provisioning", "staff_invitation"])
def test_staff_provenance_cannot_swap_platform_and_tenant_planes(
    admin_conn: PgConnection,
    provenance: str,
) -> None:
    org = _organization(admin_conn)
    principal = _principal(admin_conn, org)
    binding = _binding(admin_conn, org, principal)
    party = _party(admin_conn, org)
    actor = _principal(admin_conn, org if provenance == "root_provisioning" else None)
    with pytest.raises(Error) as error, admin_conn.transaction():
        admin_conn.execute(
            "INSERT INTO request_engine.staff_memberships "
            "(id, organization_id, principal_id, identity_binding_id, authority_anchor_party_id, "
            "established_by_principal_id, provenance_kind, provenance_reference) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (uuid4(), org, principal, binding, party, actor, provenance, uuid4().hex),
        )
    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id = %s",
        (org,),
    ).fetchone() == (0,)


def test_tenant_cannot_be_platform_grant_provenance(admin_conn: PgConnection) -> None:
    platform = _principal(admin_conn, None)
    tenant = _principal(admin_conn, _organization(admin_conn))
    with pytest.raises(Error) as error, admin_conn.transaction():
        _grant(admin_conn, None, platform, tenant)
    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants WHERE principal_id = %s",
        (platform,),
    ).fetchone() == (0,)


@pytest.mark.parametrize("surface", ["root", "staff"])
@pytest.mark.parametrize(
    "attack", ["party", "principal", "binding", "same_tenant_binding", "provenance", "valid"]
)
def test_root_and_staff_references_bind_tenant_and_principal(
    admin_conn: PgConnection,
    surface: str,
    attack: str,
) -> None:
    """Direct SQL exercises relational truth, including valid platform root origin.

    Failed writes must leave no root or seeded membership. Same-tenant binding
    substitution attacks the stronger (organization, principal, binding) FK.
    """
    org = _organization(admin_conn)
    other_org = _organization(admin_conn)
    principal = _principal(admin_conn, org)
    other_principal = _principal(admin_conn, other_org)
    party = _party(admin_conn, other_org if attack == "party" else org)
    binding_principal = principal
    binding_org = org
    if attack == "binding":
        binding_principal, binding_org = other_principal, other_org
    elif attack == "same_tenant_binding":
        binding_principal = _principal(admin_conn, org)
    binding = _binding(admin_conn, binding_org, binding_principal)
    actor = (
        other_principal
        if attack == "provenance"
        else _principal(
            admin_conn,
            None if surface == "root" else org,
        )
    )
    target = other_principal if attack == "principal" else principal

    def insert() -> None:
        if surface == "root":
            admin_conn.execute(
                "INSERT INTO request_engine.organization_root_provisioning_facts "
                "(organization_id, organization_party_id, controller_principal_id, "
                "controller_binding_id, provisioned_by_principal_id, provenance_reference) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (org, party, target, binding, actor, uuid4().hex),
            )
        else:
            admin_conn.execute(
                "INSERT INTO request_engine.staff_memberships "
                "(id, organization_id, principal_id, identity_binding_id, "
                "authority_anchor_party_id, "
                "established_by_principal_id, provenance_kind, provenance_reference) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'staff_invitation', %s)",
                (uuid4(), org, target, binding, party, actor, uuid4().hex),
            )

    if attack == "valid":
        with admin_conn.transaction():
            insert()
    else:
        with pytest.raises(Error) as error, admin_conn.transaction():
            insert()
        assert error.value.sqlstate in {"23503", "23514"}
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id = %s",
        (org,),
    ).fetchone() == (int(attack == "valid" and surface == "root"),)
    assert admin_conn.execute(
        "SELECT principal_id, identity_binding_id, established_by_principal_id "
        "FROM request_engine.staff_memberships WHERE organization_id = %s",
        (org,),
    ).fetchall() == ([(principal, binding, actor)] if attack == "valid" else [])


@pytest.mark.postgres
@pytest.mark.parametrize("surface", ["binding", "grant"])
@pytest.mark.parametrize("attack", ["foreign_tenant", "null_tenant", "platform_as_tenant"])
def test_nullable_authority_references_do_not_bypass_tenant_scope(
    admin_conn: PgConnection,
    surface: str,
    attack: str,
) -> None:
    """REPLACE duplicate catalog proof with MATCH SIMPLE null-bypass attacks.

    The catalog inventory remains in test_v3_tenant_reference_integrity. Real
    PostgreSQL guards must reject NULL tenant + tenant Principal, foreign tenant
    and platform Principal + tenant scope, even when a nullable FK is skipped.
    """
    org = _organization(admin_conn)
    principal = _principal(admin_conn, None if attack == "platform_as_tenant" else org)
    claimed_org = None if attack == "null_tenant" else _organization(admin_conn)
    if attack == "platform_as_tenant":
        claimed_org = org
    with pytest.raises(Error) as error, admin_conn.transaction():
        if surface == "binding":
            _binding(admin_conn, claimed_org, principal)
        else:
            _grant(admin_conn, claimed_org, principal, None)
    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.identity_bindings WHERE principal_id = %s), "
        "(SELECT count(*) FROM request_engine.principal_authority_grants WHERE principal_id = %s), "
        "authority_revision FROM request_engine.principals WHERE id = %s",
        (principal, principal, principal),
    ).fetchone() == (0, 0, 1)


@pytest.mark.postgres
def test_representation_has_explicit_provenance_and_no_persisted_expired_state(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    principal_id = _principal(admin_conn, organization_id)
    party_id = _party(admin_conn, organization_id)

    representation_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key,
            valid_until
        ) VALUES (
            %s, %s, %s, 'guardian', 'appointments.manage',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, party_id),
    )
    assert representation_id

    with pytest.raises(Error) as expired_error:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, status
            ) VALUES (%s, %s, %s, 'delegated', 'appointments.manage', 'expired')
            """,
            (organization_id, principal_id, party_id),
        )
    assert expired_error.value.sqlstate == "23514"

    with pytest.raises(Error) as kind_error:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key
            ) VALUES (%s, %s, %s, 'staff', 'appointments.manage')
            """,
            (organization_id, principal_id, party_id),
        )
    assert kind_error.value.sqlstate == "23514"


@pytest.mark.postgres
def test_representation_cannot_cross_tenant_boundary(admin_conn: PgConnection) -> None:
    organization_a = _organization(admin_conn)
    organization_b = _organization(admin_conn)
    principal_a = _principal(admin_conn, organization_a)
    party_b = _party(admin_conn, organization_b)

    with pytest.raises(Error) as exc_info:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key
            ) VALUES (%s, %s, %s, 'delegated', 'appointments.manage')
            """,
            (organization_a, principal_a, party_b),
        )
    assert exc_info.value.sqlstate == "23503"


@pytest.mark.postgres
def test_current_representation_is_derived_from_status_and_database_time(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    principal_id = _principal(admin_conn, organization_id)
    party_id = _party(admin_conn, organization_id)

    def insert_window(
        scope: str,
        status: str,
        from_delta: str,
        until_delta: str | None,
    ) -> UUID:
        return _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, status, valid_from, valid_until
            ) VALUES (
                %s, %s, %s, 'delegated', %s, %s,
                clock_timestamp() + %s::interval,
                CASE
                    WHEN %s::text IS NULL THEN NULL
                    ELSE clock_timestamp() + %s::interval
                END
            )
            RETURNING id
            """,
            (
                organization_id,
                principal_id,
                party_id,
                scope,
                status,
                from_delta,
                until_delta,
                until_delta,
            ),
        )

    current_id = insert_window("appointments.manage", "active", "-1 hour", "1 hour")
    insert_window("queue.manage", "active", "1 hour", "2 hours")
    insert_window("requests.submit", "active", "-2 hours", "-1 hour")
    insert_window("reminders.manage", "revoked", "-1 hour", None)

    rows = admin_conn.execute(
        """
        SELECT r.id
        FROM request_engine.representations r
        JOIN request_engine.principals p
          ON p.organization_id = r.organization_id
         AND p.id = r.principal_id
        JOIN request_engine.parties party
          ON party.organization_id = r.organization_id
         AND party.id = r.represented_party_id
        CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
        WHERE r.organization_id = %s
          AND r.principal_id = %s
          AND r.represented_party_id = %s
          AND r.scope_key = 'appointments.manage'
          AND r.status = 'active'
          AND p.active
          AND party.active
          AND r.valid_from <= clock.db_now
          AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
        """,
        (organization_id, principal_id, party_id),
    ).fetchall()

    assert rows == [(current_id,)]
