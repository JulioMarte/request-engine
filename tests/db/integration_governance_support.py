from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from agent_governance_support import (
    grant_delegable,
    issue_agent_secret,
    principal_revision,
    reset_actor,
    set_tenant_actor,
)
from psycopg import Connection

PgConnection = Connection[Any]

_INTEGRATION_CONTROL_CAPABILITIES = (
    "integration.provision",
    "integration.manage_authority",
    "integration.suspend",
)


def grant_integration_control(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
) -> None:
    for capability_key in _INTEGRATION_CONTROL_CAPABILITIES:
        grant_delegable(
            conn,
            principal_id=controller_id,
            organization_id=organization_id,
            capability_key=capability_key,
            authority_plane="tenant_control",
        )


def provision_integration(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    workload_authority_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID, str]:
    grant_integration_control(
        conn,
        organization_id=organization_id,
        controller_id=controller_id,
    )
    digest, secret = issue_agent_secret()
    integration_principal_id = uuid4()
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
            SELECT request_engine.provision_integration(
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                integration_principal_id,
                binding_id,
                workload_identity_id,
                credential_id,
                workload_authority_id,
                digest,
                digest.hex()[:16],
                datetime.now(UTC) + timedelta(days=30),
                f"integration-provision:{uuid4().hex}",
            ),
        ).fetchone()
        assert revision is not None and int(revision[0]) == 1
    finally:
        reset_actor(conn)
    token = f"{credential_id}.{secret}"
    return integration_principal_id, binding_id, workload_identity_id, credential_id, token


def transition_integration(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_id: UUID,
    integration_principal_id: UUID,
    expected_revision: int,
    target_status: str,
) -> int:
    grant_integration_control(
        conn,
        organization_id=organization_id,
        controller_id=controller_id,
    )
    set_tenant_actor(
        conn,
        organization_id=organization_id,
        principal_id=controller_id,
    )
    try:
        row = conn.execute(
            "SELECT request_engine.set_integration_status(%s, %s, %s, %s)",
            (
                integration_principal_id,
                expected_revision,
                target_status,
                f"integration-transition:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        reset_actor(conn)


def integration_revision(conn: PgConnection, integration_principal_id: UUID) -> int:
    return principal_revision(conn, integration_principal_id)
