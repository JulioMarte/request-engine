from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.adapters.db.intake_control_codec import (
    intake_state_from_json,
    intake_state_from_row,
    intake_state_to_json,
)
from request_engine.modules.queue.adapters.db.intake_control_store import load_intake_control
from request_engine.modules.queue.contracts.intake import (
    QueueIntakeControlPort,
    QueueIntakeControlState,
    QueueIntakeRevisionConflict,
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
        self, organization_id: UUID, service_queue_id: UUID
    ) -> QueueIntakeControlState:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await load_intake_control(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
                lock=False,
            )

    async def set_intake_control(
        self, request: SetQueueIntakeControlRequest
    ) -> QueueIntakeControlState:
        _validate_request(request)
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
                return intake_state_from_json(
                    cast(dict[str, object], replay["intake_control"])
                )
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
                            SET accepting = :accepting, reason = :reason,
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
            state = intake_state_from_row(cast(RowMapping, row))
            await append_audit(
                session,
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                command_name="queue.set_intake_control",
                aggregate_kind="ServiceQueue",
                aggregate_id=request.service_queue_id,
                idempotency_id=idempotency_id,
                details=intake_state_to_json(state),
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"intake_control": intake_state_to_json(state)},
            )
            return state


def _validate_request(request: SetQueueIntakeControlRequest) -> None:
    if request.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not request.idempotency_key:
        raise ValueError("idempotency_key is required")
    if request.reason is not None and not request.reason.strip():
        raise ValueError("reason cannot be blank")
    if request.effective_until is not None and request.effective_until.tzinfo is None:
        raise ValueError("effective_until must be timezone-aware")
