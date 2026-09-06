from dataclasses import replace
from typing import cast
from uuid import UUID

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def five_minute_sandbox(conn: PgConnection, sandbox: TenantSandbox) -> TenantSandbox:
    capability = conn.execute(
        "SELECT capability_id FROM request_engine.offering_resource_requirements "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.requirement_id),
    ).fetchone()
    assert capability is not None
    version = conn.execute(
        "INSERT INTO request_engine.offering_versions "
        "(organization_id,offering_id,version,duration_minutes,bookable,requestable,"
        "booking_policy,public_data) VALUES (%s,%s,2,5,true,true,%s::jsonb,'{}'::jsonb) "
        "RETURNING id",
        (sandbox.organization_id, sandbox.offering_id, '{"slot_step_minutes":5}'),
    ).fetchone()
    assert version is not None
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (sandbox.organization_id, version[0]),
    )
    requirement = conn.execute(
        "INSERT INTO request_engine.offering_resource_requirements "
        "(organization_id,offering_version_id,capability_id,ordinal,quantity) "
        "VALUES (%s,%s,%s,1,1) RETURNING id",
        (sandbox.organization_id, version[0], capability[0]),
    ).fetchone()
    assert requirement is not None
    return replace(
        sandbox,
        offering_version_id=cast(UUID, version[0]),
        requirement_id=cast(UUID, requirement[0]),
    )
