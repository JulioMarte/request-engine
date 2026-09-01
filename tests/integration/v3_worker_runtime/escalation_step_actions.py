"""Real-surface drivers and query oracles for the S3 escalation step proofs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from psycopg import Connection

from request_engine.modules.communications.adapters.db.delivery_store import (
    FinalizedDelivery,
    finalize_provider_result,
)
from request_engine.modules.communications.adapters.db.escalation_commands import (
    escalate_channel,
)
from request_engine.modules.communications.adapters.db.escalation_ladder import (
    EscalationOutcome,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.modules.communications.domain.escalation_policy import (
    validate_escalation_trigger,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

PgConnection = Connection[Any]


async def run_escalation(
    session_factory: SessionFactory,
    organization_id: UUID,
    parent_task_id: UUID,
    *,
    trigger: str = "definitive_failure",
    failure_class: str = "provider_non_retryable_failure",
) -> EscalationOutcome:
    """Run the real escalation step once under a tenant transaction."""

    validate_escalation_trigger(trigger)
    async with tenant_transaction(session_factory, organization_id) as session:
        return await escalate_channel(
            session,
            organization_id=organization_id,
            parent_task_id=parent_task_id,
            trigger=trigger,
            failure_class=failure_class,
        )


async def finalize_non_retryable_failure(
    session_factory: SessionFactory,
    organization_id: UUID,
    delivery_id: UUID,
) -> FinalizedDelivery:
    """Drive the fenced finalize with a definitive (non-retryable) failure."""

    async with tenant_transaction(session_factory, organization_id) as session:
        return await finalize_provider_result(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
            result=ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=False,
                result_data={"source": "escalation-step-test"},
            ),
        )


def child_tasks(
    conn: PgConnection,
    organization_id: UUID,
    parent_task_id: UUID,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, status, contact_point_id, dedupe_key, escalation_ordinal,
               lineage_id, parent_task_id, expires_at, recipient_party_id
        FROM request_engine.communication_tasks
        WHERE organization_id = %s AND parent_task_id = %s
        ORDER BY id
        """,
        (organization_id, parent_task_id),
    ).fetchall()
    return [dict(zip(_CHILD_KEYS, row, strict=True)) for row in rows]


_CHILD_KEYS = (
    "id",
    "status",
    "contact_point_id",
    "dedupe_key",
    "escalation_ordinal",
    "lineage_id",
    "parent_task_id",
    "expires_at",
    "recipient_party_id",
)


def ledger_rows(
    conn: PgConnection,
    organization_id: UUID,
    parent_task_id: UUID,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT trigger, from_channel, to_channel, ordinal, failure_class, child_task_id
        FROM request_engine.communication_escalations
        WHERE organization_id = %s AND parent_task_id = %s
        ORDER BY ordinal
        """,
        (organization_id, parent_task_id),
    ).fetchall()
    keys = ("trigger", "from_channel", "to_channel", "ordinal", "failure_class", "child_task_id")
    return [dict(zip(keys, row, strict=True)) for row in rows]


def outbox_payloads(
    conn: PgConnection,
    organization_id: UUID,
    event_type: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT payload FROM request_engine.outbox_messages"
        " WHERE organization_id = %s AND event_type = %s ORDER BY created_at, id",
        (organization_id, event_type),
    ).fetchall()
    return [cast(dict[str, object], row[0]) for row in rows]


def lock_escalation_barrier(blocker: PgConnection) -> None:
    """Park an escalation at its ledger read while it owns the parent lock."""

    blocker.execute("LOCK TABLE request_engine.communication_escalations IN ACCESS EXCLUSIVE MODE")
