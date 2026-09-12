from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]


def _one_uuid(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def test_staff_invitation_ignores_caller_selected_authority_anchor(
    admin_conn: PgConnection,
) -> None:
    provisioner_id = _one_uuid(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"anchor-platform-{uuid4().hex}",),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (
            %s, 'platform', 'platform', 'organization.provision', false,
            'trust_bootstrap', %s
        )
        """,
        (provisioner_id, f"anchor-root:{uuid4().hex}"),
    )
    authority_id = _one_uuid(
        admin_conn,
        """
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"anchor-native-{uuid4().hex}",),
    )

    def credentialed_identity(prefix: str) -> UUID:
        identity_id = _one_uuid(
            admin_conn,
            """
            INSERT INTO request_engine.native_identities (
                identity_authority_id, login_handle
            ) VALUES (%s, %s) RETURNING id
            """,
            (authority_id, f"{prefix}-{uuid4().hex}@example.test"),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.native_credentials (native_identity_id, verifier)
            VALUES (%s, %s)
            """,
            (identity_id, "scrypt$" + ("x" * 64)),
        )
        return identity_id

    root_identity_id = credentialed_identity("root")
    organization_id = uuid4()
    root_party_id = uuid4()
    controller_id = uuid4()
    revision_row = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (provisioner_id,),
    ).fetchone()
    assert revision_row is not None
    admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(int(revision_row[0])),),
    )
    admin_conn.execute("SET ROLE request_platform_control")
    try:
        admin_conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"anchor-tenant-{organization_id.hex}",
                "Anchor Tenant",
                root_party_id,
                controller_id,
                authority_id,
                root_identity_id,
                f"anchor-root:{uuid4().hex}",
            ),
        ).fetchone()
    finally:
        admin_conn.execute("RESET ROLE")

    staff_identity_id = credentialed_identity("staff")
    membership_id = uuid4()
    staff_principal_id = uuid4()
    binding_id = uuid4()
    caller_selected_anchor = uuid4()
    admin_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(controller_id),),
    )
    admin_conn.execute("SET ROLE request_engine_app")
    try:
        returned = admin_conn.execute(
            """
            SELECT request_engine.invite_native_staff(
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                membership_id,
                staff_principal_id,
                binding_id,
                authority_id,
                staff_identity_id,
                caller_selected_anchor,
                f"anchor-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
    finally:
        admin_conn.execute("RESET ROLE")

    anchor = admin_conn.execute(
        """
        SELECT authority_anchor_party_id
          FROM request_engine.staff_memberships
         WHERE id = %s
        """,
        (membership_id,),
    ).fetchone()
    assert anchor == (root_party_id,)
