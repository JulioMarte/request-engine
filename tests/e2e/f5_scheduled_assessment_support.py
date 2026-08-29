from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from request_engine.platform.scheduling.postgres import ScheduledActionLease

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def current_source_revision(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.recovery_source_revisions "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def lease_reassessment(
    conn: PgConnection,
    sandbox: TenantSandbox,
    revision: int,
) -> ScheduledActionLease:
    token = uuid4()
    row = conn.execute(
        "UPDATE request_engine.scheduled_actions "
        "SET status='leased',claim_token=%s,lease_until=clock_timestamp()+interval '5 minutes',"
        "attempt_count=attempt_count+1,updated_at=clock_timestamp() "
        "WHERE organization_id=%s AND dedupe_key=%s "
        "RETURNING id,organization_id,owner_module,action_type,action_version,"
        "subject_kind,subject_id,payload,attempt_count,lease_until",
        (
            token,
            sandbox.organization_id,
            f"f5-reassessment:{sandbox.queue_id}:{revision}",
        ),
    ).fetchone()
    assert row is not None
    return ScheduledActionLease(
        id=cast(UUID, row[0]),
        organization_id=cast(UUID, row[1]),
        claim_token=token,
        owner_module=cast(str, row[2]),
        action_type=cast(str, row[3]),
        action_version=cast(int, row[4]),
        subject_kind=cast(str | None, row[5]),
        subject_id=cast(UUID | None, row[6]),
        payload=cast(dict[str, object], row[7]),
        attempt_count=cast(int, row[8]),
        lease_until=cast(datetime, row[9]),
    )


def incident_revision(conn: PgConnection, sandbox: TenantSandbox) -> tuple[int, int] | None:
    row = conn.execute(
        "SELECT source_revision,revision FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s AND service_queue_id=%s AND status <> 'resolved'",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    if row is None:
        return None
    return cast(int, row[0]), cast(int, row[1])
