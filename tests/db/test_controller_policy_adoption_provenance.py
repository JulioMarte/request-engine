"""PostgreSQL backstop for platform approver provenance in adoption facts."""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_governance_support import provision_root
from psycopg import Connection
from psycopg.errors import CheckViolation

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


def test_tenant_controller_cannot_be_recorded_as_platform_approver(
    admin_conn: PgConnection,
) -> None:
    """A malformed fact must fail even if a future writer bypasses Python checks."""
    organization_id, _party_id, root_id, _authority_id = provision_root(admin_conn)
    root = admin_conn.execute(
        """
        SELECT fact.controller_binding_id, principal.authority_revision
          FROM request_engine.organization_root_provisioning_facts fact
          JOIN request_engine.principals principal
            ON principal.id = fact.controller_principal_id
         WHERE fact.organization_id = %s AND fact.controller_principal_id = %s
        """,
        (organization_id, root_id),
    ).fetchone()
    assert root is not None
    binding_id = cast(UUID, root[0])
    # The isolated fixture's platform provisioner is used only to establish the
    # valid organization/root/binding references. The guard under test concerns
    # the separate platform-approver reference, not the policy transition.
    source_policy_key = "tenant-controller-v5"
    authority_revision = cast(int, root[1])
    request_id = uuid4()
    correlation_id = uuid4()
    request_digest = "a" * 64
    intent_digest = "b" * 64
    admin_conn.execute(
        """
        INSERT INTO request_engine.controller_policy_adoption_requests(
            id,organization_id,controller_principal_id,controller_binding_id,
            source_policy_key,target_policy_key,expected_authority_revision,reason,
            idempotency_key_digest,intent_digest,correlation_id,expires_at
        ) VALUES (%s,%s,%s,%s,%s,'tenant-controller-v6',%s,'provenance backstop test',
                  %s,%s,%s,clock_timestamp()+interval '1 hour')
        """,
        (
            request_id,
            organization_id,
            root_id,
            binding_id,
            source_policy_key,
            authority_revision,
            request_digest,
            intent_digest,
            correlation_id,
        ),
    )

    with pytest.raises(CheckViolation, match="Authority provenance cannot cross tenant"):
        admin_conn.execute(
            """
            INSERT INTO request_engine.controller_policy_adoption_facts(
                request_id,organization_id,controller_principal_id,controller_binding_id,
                platform_approver_principal_id,source_policy_key,target_policy_key,
                authority_revision_before,authority_revision_after,added_capabilities,
                idempotency_key_digest,intent_digest,platform_authority_revision,correlation_id
            ) VALUES (%s,%s,%s,%s,%s,%s,'tenant-controller-v6',%s,%s,ARRAY['example.capability'],
                      %s,%s,1,%s)
            """,
            (
                request_id,
                organization_id,
                root_id,
                binding_id,
                root_id,
                source_policy_key,
                authority_revision,
                authority_revision + 1,
                request_digest,
                intent_digest,
                correlation_id,
            ),
        )

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.controller_policy_adoption_facts WHERE request_id=%s",
        (request_id,),
    ).fetchone() == (0,)
