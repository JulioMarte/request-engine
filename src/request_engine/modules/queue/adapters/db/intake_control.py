from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlPort,
    QueueIntakeControlState,
    QueueIntakeRevisionConflict,
    QueueIntakeStopped,
    SetQueueIntakeControlRequest,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


class PostgresQueueIntakeControl(QueueIntakeControlPort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_intake_control(
        self,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> QueueIntakeControlState:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await load_intake_control(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                lock=False,
            )

    async def set_intake_control(
        self,
        request: SetQueueIntakeControlRequest,
    ) -> QueueIntakeControlState:
        if request.expected_revision <= 0:
            raise ValueError("expected_revision must be positive")
        if not request.idempotency_key:
            raise ValueError("idempotency_key is required")
        if request.reason is not None and not request.reason.strip():
            raise ValueError("reason cannot be blank")
        if request.effective_until is not None:
            if request.effective_until.tzinfo is None:
                raise ValueError("effective_until must be timezone-aware")
            if request.effective_until <= datetime.now(timezone.utc):
                raise ValueError("effective_until must be in the future")

        fingerprint = command_fingerprint(
            "queue.set_intake_control.v1",
            {
                "service_queue_id": request.service_queue_id,
                "accepting": request.accepting,
                "expected_revision": request.expected_revision,
                "reason": request.reason,
                "effective_until": request.effective_until,
            },
        )
        async with tenant_transaction(self._session_factory, request.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                capability="queue.set_intake_control",
                idempotency_key=request.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _state_from_json(cast(dict[str, object], replay["intake_control"]))

            current = await load_intake_control(
                session,
                organization_id=request.organization_id,
                service_queue_id=request.service_queue_id,
                lock=True,
            )
            if current.revision != request.expected_revision:
                raise QueueIntakeRevisionConflict(
                    request.service_queue_id,
                    request.expected_revision,
                    current.revision,
                )

            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE request_engine.service_queue_intake_controls
                            SET accepting = :accepting,
                                reason = :reason,
                                effective_until = :effective_until,
                                revision = revision + 1,
                                updated_by_principal_id = :principal_id,
                                updated_at = clock_timestamp()
                            WHERE organization_id = :organization_id
                              AND service_queue_id = :service_queue_id
                            RETURNING service_queue_id, accepting, reason,
                                      effective_until, revision, updated_at
                            """
                        ),
                        {
                            "organization_id": request.organization_id,
                            "service_queue_id": request.service_queue_id,
                            "principal_id": request.principal_id,
                            "accepting": request.accepting,
                            "reason": request.reason,
                            "effective_until": request.effective_until,
                        },
                    )
                )
                .mappings()
                .one()
            )
            state = _state_from_row(row)
            await append_audit(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                command_name="queue.set_intake_control",
                aggregate_kind="ServiceQueue",
                aggregate_id=request.service_queue_id,
                idempotency_id=idempotency_id,
                details={
                    "accepting": state.accepting,
                    "reason": state.reason,
                    "effective_until": (
                        state.effective_until.isoformat() if state.effective_until is not None else None
                    ),
                    "revision": state.revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"intake_control": _state_to_json(state)},
            )
            return state


async def require_queue_accepting_intake(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> QueueIntakeControlState:
    state = await load_intake_control(
        session,
        organization_id=organization_id,
        service_queue_id=service_queue_id,
        lock=True,
    )
    if state.accepting:
        return state
    if state.effective_until is not None:
        now = cast(datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one())
        if state.effective_until <= now:
            return state
    raise QueueIntakeStopped(service_queue_id, state.reason)


async def load_intake_control(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    lock: bool,
) -> QueueIntakeControlState:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT service_queue_id, accepting, reason,
                           effective_until, revision, updated_at
                    FROM request_engine.service_queue_intake_controls
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :service_queue_id
                    """
                    + suffix
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError(f"ServiceQueue {service_queue_id} intake control is not configured")
    return _state_from_row(row)


def _state_from_row(row: object) -> QueueIntakeControlState:
    mapping = cast(dict[str, object], row)
    return QueueIntakeControlState(
        service_queue_id=cast(UUID, mapping["service_queue_id"]),
        accepting=cast(bool, mapping["accepting"]),
        reason=cast(str | None, mapping["reason"]),
        effective_until=cast(datetime | None, mapping["effective_until"]),
        revision=cast(int, mapping["revision"]),
        updated_at=cast(datetime, mapping["updated_at"]),
    )


def _state_to_json(state: QueueIntakeControlState) -> dict[str, object]:
    return {
        "service_queue_id": str(state.service_queue_id),
        "accepting": state.accepting,
        "reason": state.reason,
        "effective_until": state.effective_until.isoformat() if state.effective_until else None,
        "revision": state.revision,
        "updated_at": state.updated_at.isoformat(),
    }


def _state_from_json(payload: dict[str, object]) -> QueueIntakeControlState:
    effective_until = payload.get("effective_until")
    return QueueIntakeControlState(
        service_queue_id=UUID(cast(str, payload["service_queue_id"])),
        accepting=cast(bool, payload["accepting"]),
        reason=cast(str | None, payload.get("reason")),
        effective_until=(
            datetime.fromisoformat(cast(str, effective_until)) if effective_until is not None else None
        ),
        revision=cast(int, payload["revision"]),
        updated_at=datetime.fromisoformat(cast(str, payload["updated_at"])),
    )
