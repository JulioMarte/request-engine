"""Populated 0035-to-HEAD proof used by the isolated multidatabase runner.

A migration must not silently enlarge old controller authority or resurrect a
revocation. Create the root through its real private command before upgrading;
compare durable authority across upgrade and selected-policy replay afterwards.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection

from request_engine.platform.security.native_auth import hash_password


@dataclass(frozen=True)
class PrePolicyRoot:
    creator: UUID
    parameters: tuple[object, ...]
    result: tuple[object, ...]
    grants: tuple[tuple[object, ...], ...]
    policy: str | None = None


def _authority(conn: Connection[Any], controller: object) -> tuple[tuple[object, ...], ...]:
    return tuple(
        conn.execute(
            "SELECT id, authority_plane, capability_key, delegable, status, revision, "
            "granted_by_principal_id, provenance_kind, provenance_reference, "
            "revoked_by_principal_id, revoked_at "
            "FROM request_engine.principal_authority_grants WHERE principal_id=%s ORDER BY id",
            (controller,),
        ).fetchall()
    )


def _create_or_replay(
    conn: Connection[Any], creator: UUID, parameters: tuple[object, ...], *, policy: str | None
) -> tuple[object, ...]:
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (creator,)
    ).fetchone()
    if revision is None:
        raise RuntimeError("migration proof creator is missing")
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, true)", (str(creator),)
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, true)", (str(revision[0]),)
    )
    conn.execute("SET LOCAL ROLE request_platform_control")
    if policy is not None:
        conn.execute(
            "SELECT request_platform.select_initial_controller_policy(%s)",
            (policy,),
        )
    row = conn.execute(
        "SELECT * FROM request_platform.provision_native_organization_root"
        "(%s,%s,%s,%s,%s,%s,%s,%s)",
        parameters,
    ).fetchone()
    conn.execute("RESET ROLE")
    if row is None:
        raise RuntimeError("migration proof root command returned no result")
    return tuple(row)


def establish_pre_policy_root(
    conn: Connection[Any],
    *,
    policy: str | None = None,
) -> PrePolicyRoot:
    creator, authority, identity, organization, party, controller = (uuid4() for _ in range(6))
    # Credential preparation precedes the authoritative root transaction.
    verifier = hash_password(f"migration-proof-{uuid4().hex}")
    with conn.transaction():
        conn.execute(
            "INSERT INTO request_engine.principals "
            "(id, principal_plane, principal_kind, external_subject) "
            "VALUES (%s, 'platform', 'human', %s)",
            (creator, f"migration-proof-{creator}"),
        )
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants "
            "(principal_id, principal_plane, authority_plane, capability_key, delegable, "
            "provenance_kind, provenance_reference) "
            "VALUES (%s, 'platform', 'platform', 'organization.provision', false, "
            "'trust_bootstrap', 'isolated-migration-proof')",
            (creator,),
        )
        conn.execute(
            "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
            "VALUES (%s, 'native', %s)",
            (authority, f"isolated-migration-proof-{authority}"),
        )
        conn.execute(
            "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
            "VALUES (%s, %s, 'legacy-controller@example.test')",
            (identity, authority),
        )
        conn.execute(
            "INSERT INTO request_engine.native_credentials(native_identity_id, verifier) "
            "VALUES (%s,%s)",
            (identity, verifier),
        )
        parameters = (
            organization,
            f"legacy-clinic-{organization}",
            "Legacy Clinic",
            party,
            controller,
            authority,
            identity,
            "isolated-migration-proof",
        )
        result = _create_or_replay(conn, creator, parameters, policy=policy)
        changed = conn.execute(
            "UPDATE request_engine.principal_authority_grants SET status='revoked', "
            "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
            "WHERE principal_id=%s AND capability_key='staff.read' AND status='active'",
            (controller, controller),
        ).rowcount
        if changed != 1:
            raise RuntimeError("migration proof failed to establish a real revocation")
        grants = _authority(conn, controller)
    return PrePolicyRoot(creator, parameters, result, grants, policy)


def verify_pre_policy_root_unchanged(conn: Connection[Any], before: PrePolicyRoot) -> None:
    organization, _, _, _, controller, *_ = before.parameters
    with conn.transaction():
        policy = conn.execute(
            "SELECT initial_controller_policy_key "
            "FROM request_engine.organization_root_provisioning_facts WHERE organization_id=%s",
            (organization,),
        ).fetchone()
        if policy != (before.policy,) or _authority(conn, controller) != before.grants:
            raise RuntimeError("upgrade changed a pre-policy root's authority or policy")
        result = _create_or_replay(
            conn, before.creator, before.parameters, policy="tenant-controller-v2"
        )
        if result != before.result or _authority(conn, controller) != before.grants:
            raise RuntimeError("selected-policy replay changed a legacy root or restored authority")
        if conn.execute(
            "SELECT initial_controller_policy_key "
            "FROM request_engine.organization_root_provisioning_facts WHERE organization_id=%s",
            (organization,),
        ).fetchall() != [(before.policy,)]:
            raise RuntimeError("legacy replay duplicated the root or changed its policy")
    print("[PASS] populated pre-policy root and revocation survived upgrade and policy replay")
