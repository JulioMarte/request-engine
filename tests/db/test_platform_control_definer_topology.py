from typing import Any, cast

import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_RUNTIME = "request_platform_control"
_DEFINER = "request_platform_control_definer"
_PROVISIONER_FUNCTION = "request_platform.provision_tenant_provisioner(uuid, text, text)"
_NATIVE_PROVISIONER_FUNCTION = (
    "request_platform.provision_native_tenant_provisioner(uuid, uuid, uuid, uuid, text)"
)
_ROOT_FUNCTION = (
    "request_platform.provision_native_organization_root(uuid, text, text, uuid, uuid, "
    "uuid, uuid, text)"
)
_AUTH_LOCK_FUNCTION = "request_auth.lock_credentialed_native_identity(uuid, uuid)"
_POLICY_FUNCTION = "request_platform.select_initial_controller_policy(text)"
_OLD_ORGANIZATION_FUNCTION = "request_platform.provision_organization(uuid, text, text, text)"
_LIFECYCLE_FUNCTION = (
    "request_platform.transition_native_platform_provisioner"
    "(uuid, text, bigint, text, text, text, text)"
)
_CONTINUITY_ASSERT_FUNCTION = "request_platform.assert_other_platform_controller(uuid)"
_CONTINUITY_PREDICATE_FUNCTION = "request_platform.principal_is_effective_platform_controller(uuid)"
_EXPECTED_COLUMNS = {
    ("initial_controller_policies", "policy_key", "SELECT"),
    ("identity_bindings", "id", "SELECT"),
    ("identity_bindings", "organization_id", "SELECT"),
    ("identity_bindings", "principal_id", "SELECT"),
    ("identity_bindings", "principal_plane", "SELECT"),
    ("identity_bindings", "identity_authority_id", "SELECT"),
    ("identity_bindings", "subject_id", "SELECT"),
    ("identity_bindings", "status", "SELECT"),
    ("identity_bindings", "revision", "SELECT"),
    ("identity_bindings", "status", "UPDATE"),
    ("identity_bindings", "revision", "UPDATE"),
    ("identity_bindings", "revoked_at", "UPDATE"),
    ("principal_authority_grants", "granted_by_principal_id", "SELECT"),
    ("principal_authority_grants", "provenance_kind", "SELECT"),
    ("principal_authority_grants", "provenance_reference", "SELECT"),
    ("identity_authorities", "id", "SELECT"),
    ("identity_authorities", "kind", "SELECT"),
    ("identity_authorities", "status", "SELECT"),
    ("native_identities", "id", "SELECT"),
    ("native_identities", "identity_authority_id", "SELECT"),
    ("native_identities", "status", "SELECT"),
    ("native_credentials", "native_identity_id", "SELECT"),
    ("native_credentials", "kind", "SELECT"),
    ("native_credentials", "status", "SELECT"),
    ("identity_bindings", "id", "INSERT"),
    ("identity_bindings", "organization_id", "INSERT"),
    ("identity_bindings", "principal_id", "INSERT"),
    ("identity_bindings", "principal_plane", "INSERT"),
    ("identity_bindings", "identity_authority_id", "INSERT"),
    ("identity_bindings", "subject_id", "INSERT"),
    ("identity_bindings", "status", "INSERT"),
    ("organization_provisioning_facts", "organization_id", "INSERT"),
    ("organization_provisioning_facts", "provisioned_by_principal_id", "INSERT"),
    ("organization_provisioning_facts", "provenance_reference", "INSERT"),
    ("organization_root_provisioning_facts", "organization_id", "SELECT"),
    ("organization_root_provisioning_facts", "organization_party_id", "SELECT"),
    ("organization_root_provisioning_facts", "controller_principal_id", "SELECT"),
    ("organization_root_provisioning_facts", "controller_binding_id", "SELECT"),
    ("organization_root_provisioning_facts", "provisioned_by_principal_id", "SELECT"),
    ("organization_root_provisioning_facts", "provenance_reference", "SELECT"),
    ("organization_root_provisioning_facts", "organization_id", "INSERT"),
    ("organization_root_provisioning_facts", "organization_party_id", "INSERT"),
    ("organization_root_provisioning_facts", "controller_principal_id", "INSERT"),
    ("organization_root_provisioning_facts", "controller_binding_id", "INSERT"),
    ("organization_root_provisioning_facts", "provisioned_by_principal_id", "INSERT"),
    ("organization_root_provisioning_facts", "provenance_reference", "INSERT"),
    ("organizations", "id", "INSERT"),
    ("organizations", "organization_key", "INSERT"),
    ("organizations", "display_name", "INSERT"),
    ("parties", "id", "INSERT"),
    ("parties", "organization_id", "INSERT"),
    ("parties", "party_kind", "INSERT"),
    ("parties", "display_name", "INSERT"),
    ("party_identity_revisions", "organization_id", "INSERT"),
    ("party_identity_revisions", "party_id", "INSERT"),
    ("party_identity_revisions", "revision", "INSERT"),
    ("party_identity_revisions", "change_kind", "INSERT"),
    ("party_identity_revisions", "display_name", "INSERT"),
    ("party_identity_revisions", "active", "INSERT"),
    ("party_identity_revisions", "state", "INSERT"),
    ("principals", "id", "SELECT"),
    ("principals", "organization_id", "SELECT"),
    ("principals", "principal_plane", "SELECT"),
    ("principals", "principal_kind", "SELECT"),
    ("principals", "external_subject", "SELECT"),
    ("principals", "active", "SELECT"),
    ("principals", "authority_revision", "SELECT"),
    ("principals", "id", "INSERT"),
    ("principals", "organization_id", "INSERT"),
    ("principals", "principal_plane", "INSERT"),
    ("principals", "principal_kind", "INSERT"),
    ("principals", "external_subject", "INSERT"),
    ("principals", "authority_revision", "UPDATE"),
    ("principal_authority_grants", "principal_id", "SELECT"),
    ("principal_authority_grants", "principal_plane", "SELECT"),
    ("principal_authority_grants", "authority_plane", "SELECT"),
    ("principal_authority_grants", "capability_key", "SELECT"),
    ("principal_authority_grants", "delegable", "SELECT"),
    ("principal_authority_grants", "status", "SELECT"),
    ("principal_authority_grants", "id", "SELECT"),
    ("principal_authority_grants", "revision", "SELECT"),
    ("principal_authority_grants", "status", "UPDATE"),
    ("principal_authority_grants", "revision", "UPDATE"),
    ("principal_authority_grants", "revoked_at", "UPDATE"),
    ("principal_authority_grants", "revoked_by_principal_id", "UPDATE"),
    ("platform_authority_lifecycle_facts", "id", "SELECT"),
    ("platform_authority_lifecycle_facts", "principal_id", "SELECT"),
    ("platform_authority_lifecycle_facts", "action", "SELECT"),
    ("platform_authority_lifecycle_facts", "intent_digest", "SELECT"),
    ("platform_authority_lifecycle_facts", "revision_after", "SELECT"),
    ("platform_authority_lifecycle_facts", "actor_principal_id", "SELECT"),
    ("platform_authority_lifecycle_facts", "capability_key", "SELECT"),
    ("platform_authority_lifecycle_facts", "idempotency_key_digest", "SELECT"),
    ("platform_authority_lifecycle_facts", "id", "INSERT"),
    ("platform_authority_lifecycle_facts", "principal_id", "INSERT"),
    ("platform_authority_lifecycle_facts", "action", "INSERT"),
    ("platform_authority_lifecycle_facts", "actor_principal_id", "INSERT"),
    ("platform_authority_lifecycle_facts", "actor_authentication_method", "INSERT"),
    ("platform_authority_lifecycle_facts", "reason_code", "INSERT"),
    ("platform_authority_lifecycle_facts", "external_case_reference", "INSERT"),
    ("platform_authority_lifecycle_facts", "revision_before", "INSERT"),
    ("platform_authority_lifecycle_facts", "revision_after", "INSERT"),
    ("platform_authority_lifecycle_facts", "correlation_id", "INSERT"),
    ("platform_authority_lifecycle_facts", "capability_key", "INSERT"),
    ("platform_authority_lifecycle_facts", "idempotency_key_digest", "INSERT"),
    ("platform_authority_lifecycle_facts", "intent_digest", "INSERT"),
    ("principal_authority_grants", "organization_id", "INSERT"),
    ("principal_authority_grants", "principal_id", "INSERT"),
    ("principal_authority_grants", "principal_plane", "INSERT"),
    ("principal_authority_grants", "authority_plane", "INSERT"),
    ("principal_authority_grants", "capability_key", "INSERT"),
    ("principal_authority_grants", "delegable", "INSERT"),
    ("principal_authority_grants", "granted_by_principal_id", "INSERT"),
    ("principal_authority_grants", "provenance_kind", "INSERT"),
    ("principal_authority_grants", "provenance_reference", "INSERT"),
    ("representations", "organization_id", "INSERT"),
    ("representations", "principal_id", "INSERT"),
    ("representations", "represented_party_id", "INSERT"),
    ("representations", "authority_kind", "INSERT"),
    ("representations", "scope_key", "INSERT"),
    ("identity_recovery_cases", "delivery_destination_reference", "INSERT"),
    ("identity_recovery_cases", "evidence_reference", "INSERT"),
    ("identity_recovery_issuance_reservations", "case_id", "SELECT"),
    ("identity_recovery_issuance_reservations", "generation", "SELECT"),
    ("identity_recovery_issuance_reservations", "idempotency_key_digest", "SELECT"),
    ("identity_recovery_issuance_reservations", "case_id", "INSERT"),
    ("identity_recovery_issuance_reservations", "generation", "INSERT"),
    ("identity_recovery_issuance_reservations", "idempotency_key_digest", "INSERT"),
    ("identity_recovery_cases", "id", "INSERT"),
    ("identity_recovery_cases", "reason_code", "INSERT"),
    ("identity_recovery_cases", "requester_principal_id", "INSERT"),
    ("identity_recovery_cases", "status", "INSERT"),
    ("identity_recovery_cases", "target_native_identity_id", "INSERT"),
    ("identity_recovery_cases", "approval_expires_at", "SELECT"),
    ("identity_recovery_cases", "approved_at", "SELECT"),
    ("identity_recovery_cases", "approver_principal_id", "SELECT"),
    ("identity_recovery_cases", "consumed_at", "SELECT"),
    ("identity_recovery_cases", "created_at", "SELECT"),
    ("identity_recovery_cases", "delivery_destination_reference", "SELECT"),
    ("identity_recovery_cases", "delivery_status", "SELECT"),
    ("identity_recovery_cases", "evidence_reference", "SELECT"),
    ("identity_recovery_cases", "id", "SELECT"),
    ("identity_recovery_cases", "issuance_generation", "SELECT"),
    ("identity_recovery_cases", "issued_at", "SELECT"),
    ("identity_recovery_cases", "proof_expires_at", "SELECT"),
    ("identity_recovery_cases", "reason_code", "SELECT"),
    ("identity_recovery_cases", "recovery_intent_id", "SELECT"),
    ("identity_recovery_cases", "requester_principal_id", "SELECT"),
    ("identity_recovery_cases", "revision", "SELECT"),
    ("identity_recovery_cases", "revoke_reason_code", "SELECT"),
    ("identity_recovery_cases", "revoked_at", "SELECT"),
    ("identity_recovery_cases", "status", "SELECT"),
    ("identity_recovery_cases", "target_native_identity_id", "SELECT"),
    ("identity_recovery_cases", "updated_at", "SELECT"),
    ("identity_recovery_cases", "approval_expires_at", "UPDATE"),
    ("identity_recovery_cases", "approved_at", "UPDATE"),
    ("identity_recovery_cases", "approver_principal_id", "UPDATE"),
    ("identity_recovery_cases", "delivery_status", "UPDATE"),
    ("identity_recovery_cases", "issuance_generation", "UPDATE"),
    ("identity_recovery_cases", "issued_at", "UPDATE"),
    ("identity_recovery_cases", "proof_expires_at", "UPDATE"),
    ("identity_recovery_cases", "recovery_intent_id", "UPDATE"),
    ("identity_recovery_cases", "revision", "UPDATE"),
    ("identity_recovery_cases", "revoke_reason_code", "UPDATE"),
    ("identity_recovery_cases", "revoked_at", "UPDATE"),
    ("identity_recovery_cases", "status", "UPDATE"),
    ("identity_recovery_cases", "updated_at", "UPDATE"),
    ("identity_recovery_delivery_tickets", "case_id", "INSERT"),
    ("identity_recovery_delivery_tickets", "destination_reference", "INSERT"),
    ("identity_recovery_delivery_tickets", "expires_at", "INSERT"),
    ("identity_recovery_delivery_tickets", "generation", "INSERT"),
    ("identity_recovery_delivery_tickets", "id", "INSERT"),
    ("identity_recovery_delivery_tickets", "secret_digest", "INSERT"),
    ("identity_recovery_delivery_tickets", "secret_reference", "INSERT"),
    ("identity_recovery_delivery_tickets", "status", "INSERT"),
    ("identity_recovery_delivery_tickets", "attempt_count", "SELECT"),
    ("identity_recovery_delivery_tickets", "case_id", "SELECT"),
    ("identity_recovery_delivery_tickets", "claim_token", "SELECT"),
    ("identity_recovery_delivery_tickets", "created_at", "SELECT"),
    ("identity_recovery_delivery_tickets", "delivered_at", "SELECT"),
    ("identity_recovery_delivery_tickets", "destination_reference", "SELECT"),
    ("identity_recovery_delivery_tickets", "expires_at", "SELECT"),
    ("identity_recovery_delivery_tickets", "generation", "SELECT"),
    ("identity_recovery_delivery_tickets", "id", "SELECT"),
    ("identity_recovery_delivery_tickets", "last_error_class", "SELECT"),
    ("identity_recovery_delivery_tickets", "lease_until", "SELECT"),
    ("identity_recovery_delivery_tickets", "max_attempts", "SELECT"),
    ("identity_recovery_delivery_tickets", "next_attempt_at", "SELECT"),
    ("identity_recovery_delivery_tickets", "secret_digest", "SELECT"),
    ("identity_recovery_delivery_tickets", "secret_reference", "SELECT"),
    ("identity_recovery_delivery_tickets", "status", "SELECT"),
    ("identity_recovery_delivery_tickets", "updated_at", "SELECT"),
    ("identity_recovery_delivery_tickets", "attempt_count", "UPDATE"),
    ("identity_recovery_delivery_tickets", "claim_token", "UPDATE"),
    ("identity_recovery_delivery_tickets", "delivered_at", "UPDATE"),
    ("identity_recovery_delivery_tickets", "last_error_class", "UPDATE"),
    ("identity_recovery_delivery_tickets", "lease_until", "UPDATE"),
    ("identity_recovery_delivery_tickets", "next_attempt_at", "UPDATE"),
    ("identity_recovery_delivery_tickets", "status", "UPDATE"),
    ("identity_recovery_delivery_tickets", "updated_at", "UPDATE"),
    ("native_recovery_intents", "id", "SELECT"),
    ("native_recovery_intents", "status", "SELECT"),
    ("native_recovery_intents", "revoked_at", "UPDATE"),
    ("native_recovery_intents", "status", "UPDATE"),
    ("platform_identity_recovery_facts", "action", "INSERT"),
    ("platform_identity_recovery_facts", "actor_authentication_method", "INSERT"),
    ("platform_identity_recovery_facts", "actor_principal_id", "INSERT"),
    ("platform_identity_recovery_facts", "capability_key", "INSERT"),
    ("platform_identity_recovery_facts", "case_id", "INSERT"),
    ("platform_identity_recovery_facts", "correlation_id", "INSERT"),
    ("platform_identity_recovery_facts", "external_case_reference", "INSERT"),
    ("platform_identity_recovery_facts", "id", "INSERT"),
    ("platform_identity_recovery_facts", "idempotency_key_digest", "INSERT"),
    ("platform_identity_recovery_facts", "intent_digest", "INSERT"),
    ("platform_identity_recovery_facts", "reason_code", "INSERT"),
    ("platform_identity_recovery_facts", "revision_after", "INSERT"),
    ("platform_identity_recovery_facts", "revision_before", "INSERT"),
    ("platform_identity_recovery_facts", "action", "SELECT"),
    ("platform_identity_recovery_facts", "actor_principal_id", "SELECT"),
    ("platform_identity_recovery_facts", "capability_key", "SELECT"),
    ("platform_identity_recovery_facts", "case_id", "SELECT"),
    ("platform_identity_recovery_facts", "id", "SELECT"),
    ("platform_identity_recovery_facts", "idempotency_key_digest", "SELECT"),
    ("platform_identity_recovery_facts", "intent_digest", "SELECT"),
    ("platform_identity_recovery_facts", "revision_after", "SELECT"),
    ("native_identities", "revision", "SELECT"),
    ("native_identities", "session_epoch", "SELECT"),
    ("native_identities", "disabled_at", "SELECT"),
    ("native_identities", "updated_at", "SELECT"),
    ("native_identities", "status", "UPDATE"),
    ("native_identities", "session_epoch", "UPDATE"),
    ("native_identities", "revision", "UPDATE"),
    ("native_identities", "updated_at", "UPDATE"),
    ("native_identities", "disabled_at", "UPDATE"),
    ("native_credentials", "revision", "SELECT"),
    ("native_credentials", "status", "UPDATE"),
    ("native_credentials", "revision", "UPDATE"),
    ("native_credentials", "revoked_at", "UPDATE"),
    ("native_recovery_intents", "native_identity_id", "SELECT"),
    ("native_sessions", "native_identity_id", "SELECT"),
    ("native_sessions", "status", "SELECT"),
    ("native_sessions", "status", "UPDATE"),
    ("native_sessions", "revoked_at", "UPDATE"),
    ("native_sessions", "revocation_reason", "UPDATE"),
    ("platform_identity_disable_facts", "actor_principal_id", "INSERT"),
    ("platform_identity_disable_facts", "affected_platform", "INSERT"),
    ("platform_identity_disable_facts", "affected_tenant_count", "INSERT"),
    ("platform_identity_disable_facts", "capability_key", "INSERT"),
    ("platform_identity_disable_facts", "correlation_id", "INSERT"),
    ("platform_identity_disable_facts", "external_case_reference", "INSERT"),
    ("platform_identity_disable_facts", "idempotency_key_digest", "INSERT"),
    ("platform_identity_disable_facts", "intent_digest", "INSERT"),
    ("platform_identity_disable_facts", "native_authority_id", "INSERT"),
    ("platform_identity_disable_facts", "native_identity_id", "INSERT"),
    ("platform_identity_disable_facts", "reason_code", "INSERT"),
    ("platform_identity_disable_facts", "revision_after", "INSERT"),
    ("platform_identity_disable_facts", "revision_before", "INSERT"),
    ("platform_identity_disable_facts", "actor_principal_id", "SELECT"),
    ("platform_identity_disable_facts", "affected_platform", "SELECT"),
    ("platform_identity_disable_facts", "affected_tenant_count", "SELECT"),
    ("platform_identity_disable_facts", "capability_key", "SELECT"),
    ("platform_identity_disable_facts", "id", "SELECT"),
    ("platform_identity_disable_facts", "idempotency_key_digest", "SELECT"),
    ("platform_identity_disable_facts", "intent_digest", "SELECT"),
    ("platform_identity_disable_facts", "native_identity_id", "SELECT"),
    ("platform_identity_disable_facts", "revision_after", "SELECT"),
    ("platform_instance", "singleton_key", "SELECT"),
    ("platform_instance", "id", "SELECT"),
    ("platform_instance", "state", "SELECT"),
    ("platform_instance", "revision", "SELECT"),
    ("platform_instance", "built_in_native_authority_id", "SELECT"),
    ("platform_instance", "built_in_workload_authority_id", "SELECT"),
    ("platform_instance", "created_at", "SELECT"),
    ("platform_instance", "claimed_at", "SELECT"),
    ("platform_instance", "initial_owner_principal_id", "SELECT"),
    ("platform_instance", "claim_provenance", "SELECT"),
    ("setup_sessions", "id", "SELECT"),
    ("setup_sessions", "instance_id", "SELECT"),
    ("setup_sessions", "token_digest", "SELECT"),
    ("setup_sessions", "token_fingerprint", "SELECT"),
    ("setup_sessions", "status", "SELECT"),
    ("setup_sessions", "mode", "SELECT"),
    ("setup_sessions", "revision", "SELECT"),
    ("setup_sessions", "created_at", "SELECT"),
    ("setup_sessions", "expires_at", "SELECT"),
    ("setup_sessions", "consumed_at", "SELECT"),
    ("setup_sessions", "revoked_at", "SELECT"),
    ("setup_sessions", "id", "INSERT"),
    ("setup_sessions", "instance_id", "INSERT"),
    ("setup_sessions", "token_digest", "INSERT"),
    ("setup_sessions", "token_fingerprint", "INSERT"),
    ("setup_sessions", "mode", "INSERT"),
    ("setup_sessions", "expires_at", "INSERT"),
}


def test_platform_control_roles_have_exact_elevation(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
          FROM pg_roles WHERE rolname IN (%s, %s) ORDER BY rolname
        """,
        (_RUNTIME, _DEFINER),
    ).fetchall()
    assert rows == [
        (_RUNTIME, False, False, False, False, False),
        (_DEFINER, False, False, True, False, False),
    ]


def test_platform_control_roles_have_no_memberships(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        """
        SELECT parent.rolname, member.rolname
          FROM pg_auth_members membership
          JOIN pg_roles parent ON parent.oid = membership.roleid
          JOIN pg_roles member ON member.oid = membership.member
         WHERE parent.rolname IN (%s, %s) OR member.rolname IN (%s, %s)
        """,
        (_RUNTIME, _DEFINER, _RUNTIME, _DEFINER),
    ).fetchall()
    assert rows == []


def test_platform_control_definer_has_only_reviewed_columns(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT table_name, column_name, privilege_type
          FROM information_schema.column_privileges
         WHERE grantee = %s AND table_schema = 'request_engine'
        """,
        (_DEFINER,),
    ).fetchall()
    actual = {
        (cast(str, table), cast(str, column), cast(str, privilege))
        for table, column, privilege in rows
    }
    assert actual == _EXPECTED_COLUMNS
    assert admin_conn.execute(
        """
            SELECT table_name, privilege_type
              FROM information_schema.role_table_grants
             WHERE grantee = %s AND table_schema = 'request_engine'
            """,
        (_DEFINER,),
    ).fetchall() == [("identity_recovery_issuance_reservations", "DELETE")]


def test_platform_control_definer_uses_native_auth_only_through_lock_boundary(
    admin_conn: PgConnection,
) -> None:
    assert admin_conn.execute(
        "SELECT has_schema_privilege(%s, 'request_auth', 'USAGE')",
        (_DEFINER,),
    ).fetchone() == (True,)
    assert admin_conn.execute(
        "SELECT has_schema_privilege(%s, 'request_auth', 'CREATE')",
        (_DEFINER,),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
        (_DEFINER, _AUTH_LOCK_FUNCTION),
    ).fetchone() == (True,)
    for function in (_CONTINUITY_ASSERT_FUNCTION, _CONTINUITY_PREDICATE_FUNCTION):
        assert admin_conn.execute(
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            (_DEFINER, function),
        ).fetchone() == (True,)
    for role in (_RUNTIME, "request_engine_app", "public"):
        assert admin_conn.execute(
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            (role, _AUTH_LOCK_FUNCTION),
        ).fetchone() == (False,)
        for function in (_CONTINUITY_ASSERT_FUNCTION, _CONTINUITY_PREDICATE_FUNCTION):
            assert admin_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                (role, function),
            ).fetchone() == (False,)


def test_only_platform_control_runtime_can_execute_commands(
    admin_conn: PgConnection,
) -> None:
    for function in (
        _PROVISIONER_FUNCTION,
        _NATIVE_PROVISIONER_FUNCTION,
        _ROOT_FUNCTION,
        _POLICY_FUNCTION,
        _LIFECYCLE_FUNCTION,
    ):
        assert admin_conn.execute(
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            (_RUNTIME, function),
        ).fetchone() == (True,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('request_engine_app', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)
        assert admin_conn.execute(
            "SELECT has_function_privilege('public', %s, 'EXECUTE')",
            (function,),
        ).fetchone() == (False,)

    assert admin_conn.execute(
        "SELECT to_regprocedure(%s)",
        (_OLD_ORGANIZATION_FUNCTION,),
    ).fetchone() == (None,)
