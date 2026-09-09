from typing import Any, cast
from uuid import UUID, uuid4

from httpx import AsyncClient
from psycopg import Connection

PgConnection = Connection[Any]


def grant_agent_policy_authority(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_principal_id: UUID,
) -> None:
    """Grant the tenant controller the agent policy governance capabilities."""

    for capability in ("agent.policy.read", "agent.manage_policy"):
        conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                %s, %s, 'tenant', 'tenant_control', %s, false, %s,
                'authority_management', %s
            )
            """,
            (
                organization_id,
                controller_principal_id,
                capability,
                controller_principal_id,
                f"agent-policy-grant:{uuid4().hex}",
            ),
        )


async def provision_agent_policy(
    client: AsyncClient,
    *,
    controller_headers: dict[str, str],
    agent_principal_id: UUID,
    allowed_capabilities: list[str],
    denied_capabilities: list[str] | None = None,
    risk_ceiling: str = "low_impact_write",
    max_mutations_per_minute: int = 60,
    provenance_reference: str = "e2e-agent-policy",
) -> dict[str, object]:
    """Replace an agent tool/risk policy through the governance HTTP surface."""

    response = await client.put(
        f"/v1/agents/{agent_principal_id}/policy",
        headers={**controller_headers, "Idempotency-Key": f"agent-policy-{uuid4().hex}"},
        json={
            "allowed_capabilities": list(allowed_capabilities),
            "denied_capabilities": list(denied_capabilities or ()),
            "risk_ceiling": risk_ceiling,
            "max_mutations_per_minute": max_mutations_per_minute,
            "provenance_reference": provenance_reference,
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())
