import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.adapters.db.dispatch_actions import (
    DISPATCH_ACTION_TYPE as DISPATCH_ACTION_TYPE,
)
from request_engine.modules.communications.adapters.db.dispatch_actions import (
    DISPATCH_ACTION_VERSION as DISPATCH_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.escalation_triggers import (
    close_task_failed_and_escalate,
    resolve_route_or_escalate_unreachable,
)
from request_engine.modules.communications.adapters.db.reconcile_scheduling import (
    RECONCILE_ACTION_TYPE as RECONCILE_ACTION_TYPE,
)
from request_engine.modules.communications.adapters.db.reconcile_scheduling import (
    RECONCILE_ACTION_VERSION as RECONCILE_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reconcile_scheduling import (
    ensure_reconciliation,
)
from request_engine.modules.communications.application.errors import (
    CommunicationDeliveryNotFound,
    CommunicationTaskNotFound,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.modules.communications.domain.delivery_policy import parse_delivery_policy
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action


class DeliveryWorkKind(StrEnum):
    SEND = "send"
    LOOKUP = "lookup"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class PreparedDeliveryWork:
    kind: DeliveryWorkKind
    communication_task_id: UUID
    delivery_id: UUID | None
    send_request: ProviderSendRequest | None = None
    lookup_request: ProviderLookupRequest | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FinalizedDelivery:
    communication_task_id: UUID
    delivery_id: UUID
    status: ProviderDeliveryStatus
    retryable: bool
    task_terminal: bool


def _skip_work(communication_task_id: UUID, skip_reason: str) -> PreparedDeliveryWork:
    return PreparedDeliveryWork(
        kind=DeliveryWorkKind.SKIP,
        communication_task_id=communication_task_id,
        delivery_id=None,
        skip_reason=skip_reason,
    )


async def fail_poisoned_communication_task(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    scheduled_action_id: UUID,
    reason: str,
) -> bool:
    """Terminalize a task whose only executable dispatch intent is poison work."""

    row = (
        await session.execute(
            text(
                """
                SELECT status
                FROM request_engine.communication_tasks
                WHERE organization_id = :organization_id
                  AND id = :communication_task_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "communication_task_id": communication_task_id,
            },
        )
    ).one_or_none()
    if row is None or cast(str, row[0]) in {"completed", "cancelled", "failed"}:
        return False

    await _mark_task_failed(session, organization_id, communication_task_id)
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type="communication.task_failed.v1",
        aggregate_kind="CommunicationTask",
        aggregate_id=communication_task_id,
        payload={
            "communication_task_id": str(communication_task_id),
            "scheduled_action_id": str(scheduled_action_id),
            "reason": reason,
        },
    )
    return True


async def prepare_dispatch(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    configured_provider_keys: Collection[str] = (),
) -> PreparedDeliveryWork:
    task = await _lock_task(session, organization_id, communication_task_id)
    task_status = cast(str, task["status"])
    if task_status in {"completed", "cancelled", "failed"}:
        return _skip_work(communication_task_id, f"task_{task_status}")

    db_now = await _database_now(session)
    expires_at = cast(datetime | None, task["expires_at"])
    if expires_at is not None and expires_at <= db_now:
        await close_task_failed_and_escalate(
            session,
            organization_id=organization_id,
            communication_task_id=communication_task_id,
            payload={
                "communication_task_id": str(communication_task_id),
                "reason": "expired_before_delivery",
            },
            trigger="delivery_deadline_missed",
        )
        return _skip_work(communication_task_id, "task_expired")

    latest = await _latest_delivery(session, organization_id, communication_task_id)
    if latest is not None:
        latest_status = cast(str, latest["status"])
        if latest_status in {"attempting", "accepted", "ambiguous"}:
            return PreparedDeliveryWork(
                kind=DeliveryWorkKind.LOOKUP,
                communication_task_id=communication_task_id,
                delivery_id=cast(UUID, latest["id"]),
                lookup_request=_lookup_request(latest),
            )
        if latest_status == "delivered":
            await _set_task_status(session, organization_id, communication_task_id, "completed")
            return PreparedDeliveryWork(
                kind=DeliveryWorkKind.SKIP,
                communication_task_id=communication_task_id,
                delivery_id=cast(UUID, latest["id"]),
                skip_reason="already_delivered",
            )
        if latest_status == "failed" and not _delivery_retryable(latest):
            await _mark_task_failed(session, organization_id, communication_task_id)
            return PreparedDeliveryWork(
                kind=DeliveryWorkKind.SKIP,
                communication_task_id=communication_task_id,
                delivery_id=cast(UUID, latest["id"]),
                skip_reason="non_retryable_failure",
            )
        if latest_status == "failed" and await _future_dispatch_exists(
            session,
            organization_id=organization_id,
            communication_task_id=communication_task_id,
            db_now=db_now,
        ):
            return PreparedDeliveryWork(
                kind=DeliveryWorkKind.SKIP,
                communication_task_id=communication_task_id,
                delivery_id=cast(UUID, latest["id"]),
                skip_reason="retry_already_scheduled",
            )

    policy = parse_delivery_policy(cast(dict[str, object], task["channel_policy"]))
    resolved = await resolve_route_or_escalate_unreachable(
        session,
        organization_id=organization_id,
        task=task,
        policy=policy,
        configured_provider_keys=configured_provider_keys,
    )
    if resolved is None:
        return _skip_work(communication_task_id, "recipient_channel_unreachable")
    route, provider_key, contact_point = resolved
    if task["contact_point_id"] is None:
        await session.execute(
            text(
                """
                UPDATE request_engine.communication_tasks
                SET contact_point_id = :contact_point_id,
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :communication_task_id
                """
            ),
            {
                "organization_id": organization_id,
                "communication_task_id": communication_task_id,
                "contact_point_id": contact_point["id"],
            },
        )

    attempt_no = 1 if latest is None else cast(int, latest["attempt_no"]) + 1
    provider_idempotency_key = f"communication:{communication_task_id}:attempt:{attempt_no}"
    delivery = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.communication_deliveries (
                        organization_id,
                        communication_task_id,
                        attempt_no,
                        channel,
                        provider_key,
                        provider_idempotency_key,
                        status,
                        result_data
                    ) VALUES (
                        :organization_id,
                        :communication_task_id,
                        :attempt_no,
                        :channel,
                        :provider_key,
                        :provider_idempotency_key,
                        'attempting',
                        CAST(:result_data AS jsonb)
                    )
                    RETURNING *
                    """
                ),
                {
                    "organization_id": organization_id,
                    "communication_task_id": communication_task_id,
                    "attempt_no": attempt_no,
                    "channel": route.channel,
                    "provider_key": provider_key,
                    "provider_idempotency_key": provider_idempotency_key,
                    "result_data": json.dumps(
                        {
                            "contact_point_id": str(contact_point["id"]),
                            "destination": contact_point["normalized_value"],
                        },
                        separators=(",", ":"),
                    ),
                },
            )
        )
        .mappings()
        .one()
    )
    if task_status == "pending":
        await session.execute(
            text(
                """
                UPDATE request_engine.communication_tasks
                SET status = 'delivering',
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :communication_task_id
                  AND status = 'pending'
                """
            ),
            {
                "organization_id": organization_id,
                "communication_task_id": communication_task_id,
            },
        )

    return PreparedDeliveryWork(
        kind=DeliveryWorkKind.SEND,
        communication_task_id=communication_task_id,
        delivery_id=cast(UUID, delivery["id"]),
        send_request=ProviderSendRequest(
            delivery_id=cast(UUID, delivery["id"]),
            communication_task_id=communication_task_id,
            provider_key=provider_key,
            provider_idempotency_key=provider_idempotency_key,
            channel=route.channel,
            destination=cast(str, contact_point["normalized_value"]),
            contact_point_id=cast(UUID, contact_point["id"]),
            template_key=cast(str, task["template_key"]),
            template_version=cast(int, task["template_version"]),
            render_context=cast(dict[str, object], task["render_context"]),
            expires_at=expires_at,
            reconcile_after_seconds=policy.reconcile_after_seconds,
        ),
    )


async def prepare_reconciliation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    delivery_id: UUID,
) -> PreparedDeliveryWork:
    delivery = await _lock_delivery(session, organization_id, delivery_id)
    task_id = cast(UUID, delivery["communication_task_id"])
    task = await _lock_task(session, organization_id, task_id)
    task_status = cast(str, task["status"])
    if task_status in {"completed", "cancelled", "failed"}:
        return PreparedDeliveryWork(
            kind=DeliveryWorkKind.SKIP,
            communication_task_id=task_id,
            delivery_id=delivery_id,
            skip_reason=f"task_{task_status}",
        )
    delivery_status = cast(str, delivery["status"])
    if delivery_status == "delivered":
        await _set_task_status(session, organization_id, task_id, "completed")
        return PreparedDeliveryWork(
            kind=DeliveryWorkKind.SKIP,
            communication_task_id=task_id,
            delivery_id=delivery_id,
            skip_reason="already_delivered",
        )
    if delivery_status == "failed" and not _delivery_retryable(delivery):
        await _mark_task_failed(session, organization_id, task_id)
        return PreparedDeliveryWork(
            kind=DeliveryWorkKind.SKIP,
            communication_task_id=task_id,
            delivery_id=delivery_id,
            skip_reason="non_retryable_failure",
        )
    db_now = await _database_now(session)
    expires_at = cast(datetime | None, task["expires_at"])
    if expires_at is not None and expires_at <= db_now:
        await close_task_failed_and_escalate(
            session,
            organization_id=organization_id,
            communication_task_id=task_id,
            payload={
                "communication_task_id": str(task_id),
                "delivery_id": str(delivery_id),
                "reason": "delivery_deadline_exceeded",
            },
            trigger="delivery_deadline_missed",
        )
        return PreparedDeliveryWork(
            kind=DeliveryWorkKind.SKIP,
            communication_task_id=task_id,
            delivery_id=delivery_id,
            skip_reason="task_expired",
        )
    if delivery_status == "failed":
        return PreparedDeliveryWork(
            kind=DeliveryWorkKind.SKIP,
            communication_task_id=task_id,
            delivery_id=delivery_id,
            skip_reason="retryable_failure_requires_dispatch",
        )
    return PreparedDeliveryWork(
        kind=DeliveryWorkKind.LOOKUP,
        communication_task_id=task_id,
        delivery_id=delivery_id,
        lookup_request=_lookup_request(delivery),
    )


async def finalize_provider_result(
    session: AsyncSession,
    *,
    organization_id: UUID,
    delivery_id: UUID,
    result: ProviderDeliveryResult,
) -> FinalizedDelivery:
    delivery = await _lock_delivery(session, organization_id, delivery_id)
    task_id = cast(UUID, delivery["communication_task_id"])
    task = await _lock_task(session, organization_id, task_id)
    current_status = cast(str, delivery["status"])

    if current_status == "delivered":
        return FinalizedDelivery(
            communication_task_id=task_id,
            delivery_id=delivery_id,
            status=ProviderDeliveryStatus.DELIVERED,
            retryable=False,
            task_terminal=True,
        )
    if current_status == "failed":
        current_retryable = _delivery_retryable(delivery)
        if not current_retryable or result.status is not ProviderDeliveryStatus.DELIVERED:
            return FinalizedDelivery(
                communication_task_id=task_id,
                delivery_id=delivery_id,
                status=ProviderDeliveryStatus.FAILED,
                retryable=current_retryable,
                task_terminal=not current_retryable or cast(str, task["status"]) == "failed",
            )

    effective = result
    if result.status is ProviderDeliveryStatus.NOT_FOUND:
        effective = ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            provider_message_id=result.provider_message_id,
            retryable=True,
            result_data={**result.result_data, "reconciliation": "not_found"},
        )

    db_now = await _database_now(session)
    result_data = dict(effective.result_data)
    result_data["retryable"] = effective.retryable
    await session.execute(
        text(
            """
            UPDATE request_engine.communication_deliveries
            SET status = :status,
                provider_message_id = COALESCE(:provider_message_id, provider_message_id),
                result_data = result_data || CAST(:result_data AS jsonb),
                completed_at = :completed_at,
                updated_at = :completed_at
            WHERE organization_id = :organization_id
              AND id = :delivery_id
            """
        ),
        {
            "organization_id": organization_id,
            "delivery_id": delivery_id,
            "status": effective.status.value,
            "provider_message_id": effective.provider_message_id,
            "result_data": json.dumps(result_data, default=str, separators=(",", ":")),
            "completed_at": db_now,
        },
    )

    task_terminal = False
    policy = parse_delivery_policy(cast(dict[str, object], task["channel_policy"]))
    if effective.status is ProviderDeliveryStatus.DELIVERED:
        await _set_task_status(session, organization_id, task_id, "completed")
        task_terminal = True
        await append_outbox(
            session,
            organization_id=organization_id,
            event_type="communication.task_completed.v1",
            aggregate_kind="CommunicationTask",
            aggregate_id=task_id,
            payload={
                "communication_task_id": str(task_id),
                "delivery_id": str(delivery_id),
                "provider_message_id": effective.provider_message_id,
            },
        )
    elif effective.status is ProviderDeliveryStatus.FAILED:
        if effective.retryable:
            await _set_task_status(session, organization_id, task_id, "pending")
            await _schedule_retry_dispatch(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
                source_delivery_id=delivery_id,
                execute_at=db_now + timedelta(seconds=policy.retry_after_seconds),
            )
        else:
            await close_task_failed_and_escalate(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
                payload={
                    "communication_task_id": str(task_id),
                    "delivery_id": str(delivery_id),
                    "reason": "provider_non_retryable_failure",
                },
                trigger="definitive_failure",
            )
            task_terminal = True
    else:
        await ensure_reconciliation(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
            db_now=db_now,
            delay_seconds=policy.reconcile_after_seconds,
        )

    return FinalizedDelivery(
        communication_task_id=task_id,
        delivery_id=delivery_id,
        status=effective.status,
        retryable=effective.retryable,
        task_terminal=task_terminal,
    )


async def _lock_task(
    session: AsyncSession,
    organization_id: UUID,
    communication_task_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.communication_tasks
                    WHERE organization_id = :organization_id
                      AND id = :communication_task_id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "communication_task_id": communication_task_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise CommunicationTaskNotFound(communication_task_id)
    return row


async def _lock_delivery(
    session: AsyncSession,
    organization_id: UUID,
    delivery_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.communication_deliveries
                    WHERE organization_id = :organization_id
                      AND id = :delivery_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "delivery_id": delivery_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise CommunicationDeliveryNotFound(delivery_id)
    return row


async def _latest_delivery(
    session: AsyncSession,
    organization_id: UUID,
    communication_task_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT *
                    FROM request_engine.communication_deliveries
                    WHERE organization_id = :organization_id
                      AND communication_task_id = :communication_task_id
                    ORDER BY attempt_no DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "communication_task_id": communication_task_id,
                },
            )
        )
        .mappings()
        .first()
    )


def _lookup_request(delivery: RowMapping) -> ProviderLookupRequest:
    return ProviderLookupRequest(
        delivery_id=cast(UUID, delivery["id"]),
        communication_task_id=cast(UUID, delivery["communication_task_id"]),
        provider_key=cast(str, delivery["provider_key"]),
        provider_idempotency_key=cast(str, delivery["provider_idempotency_key"]),
        provider_message_id=cast(str | None, delivery["provider_message_id"]),
    )


def _delivery_retryable(delivery: RowMapping) -> bool:
    result_data = cast(dict[str, object], delivery["result_data"])
    return result_data.get("retryable") is True


async def _future_dispatch_exists(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    db_now: datetime,
) -> bool:
    return cast(
        bool,
        (
            await session.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM request_engine.scheduled_actions
                        WHERE organization_id = :organization_id
                          AND owner_module = 'communications'
                          AND action_type = :action_type
                          AND action_version = :action_version
                          AND subject_kind = 'CommunicationTask'
                          AND subject_id = :communication_task_id
                          AND CASE
                              WHEN pg_catalog.pg_input_is_valid(
                                  payload ->> 'communication_task_id',
                                  'uuid'
                              )
                              THEN (payload ->> 'communication_task_id')::uuid
                                   = :communication_task_id
                              ELSE false
                          END
                          AND status IN ('pending', 'leased')
                          AND attempt_count < max_attempts
                          AND execute_at > :db_now
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "action_type": DISPATCH_ACTION_TYPE,
                    "action_version": DISPATCH_ACTION_VERSION,
                    "communication_task_id": communication_task_id,
                    "db_now": db_now,
                },
            )
        ).scalar_one(),
    )


async def _schedule_retry_dispatch(
    session: AsyncSession,
    *,
    organization_id: UUID,
    communication_task_id: UUID,
    source_delivery_id: UUID,
    execute_at: datetime,
) -> None:
    await schedule_action(
        session,
        organization_id=organization_id,
        owner_module="communications",
        action_type=DISPATCH_ACTION_TYPE,
        action_version=DISPATCH_ACTION_VERSION,
        subject_kind="CommunicationTask",
        subject_id=communication_task_id,
        dedupe_key=(
            f"communications:dispatch:{communication_task_id}:after:{source_delivery_id}:v1"
        ),
        execute_at=execute_at,
        payload={"communication_task_id": str(communication_task_id)},
        max_attempts=8,
    )


async def _mark_task_failed(
    session: AsyncSession,
    organization_id: UUID,
    communication_task_id: UUID,
) -> None:
    await _set_task_status(session, organization_id, communication_task_id, "failed")


async def _set_task_status(
    session: AsyncSession,
    organization_id: UUID,
    communication_task_id: UUID,
    status: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.communication_tasks
            SET status = :status,
                revision = CASE
                    WHEN status IS DISTINCT FROM :status THEN revision + 1
                    ELSE revision
                END,
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND id = :communication_task_id
            """
        ),
        {
            "organization_id": organization_id,
            "communication_task_id": communication_task_id,
            "status": status,
        },
    )


async def _database_now(session: AsyncSession) -> datetime:
    return cast(
        datetime,
        (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
    )
