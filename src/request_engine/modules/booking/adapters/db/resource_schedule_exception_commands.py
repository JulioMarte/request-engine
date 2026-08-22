from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.booking.application.commands.set_resource_schedule_exception import (
    ResourceScheduleExceptionState,
    SetResourceScheduleExceptionCommand,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
)
from request_engine.modules.booking.domain.availability import require_aware_utc
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_operational_authority,
)


class PostgresResourceScheduleExceptionCommands:
    """Semantic Resource-wide exception writes over the released V3 relation."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_resource_schedule_exception(
        self,
        command: SetResourceScheduleExceptionCommand,
    ) -> ResourceScheduleExceptionState:
        start_at = require_aware_utc(command.start_at, "start_at")
        end_at = require_aware_utc(command.end_at, "end_at")
        if end_at <= start_at:
            raise ValueError("end_at must be after start_at")
        fingerprint = command_fingerprint(
            "booking.set_resource_schedule_exception",
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "exception_id": command.exception_id,
                "start_at": start_at,
                "end_at": end_at,
                "exception_kind": command.exception_kind,
                "reason": command.reason,
                "expected_resource_availability_revision": (
                    command.expected_resource_availability_revision
                ),
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="booking.set_resource_schedule_exception",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(cast(dict[str, object], replay["exception"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                resource = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT id, active, availability_revision
                                FROM request_engine.resources
                                WHERE organization_id = :organization_id
                                  AND id = :resource_id
                                FOR UPDATE
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if resource is None:
                    raise ContextualConfigurationConflict(
                        "Resource is missing or belongs to another Organization"
                    )
                if not cast(bool, resource["active"]):
                    raise ContextualConfigurationConflict(
                        "Resource must be active to configure schedule exceptions"
                    )
                current_revision = cast(int, resource["availability_revision"])
                if current_revision != command.expected_resource_availability_revision:
                    raise ResourceAvailabilityRevisionConflict(
                        command.resource_id,
                        command.expected_resource_availability_revision,
                        current_revision,
                    )

                if command.exception_id is None:
                    exception_id = cast(
                        UUID,
                        (
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO request_engine.schedule_exceptions (
                                        organization_id,
                                        resource_id,
                                        during,
                                        exception_kind,
                                        reason
                                    ) VALUES (
                                        :organization_id,
                                        :resource_id,
                                        tstzrange(:start_at, :end_at, '[)'),
                                        :exception_kind,
                                        :reason
                                    )
                                    RETURNING id
                                    """
                                ),
                                {
                                    "organization_id": command.organization_id,
                                    "resource_id": command.resource_id,
                                    "start_at": start_at,
                                    "end_at": end_at,
                                    "exception_kind": command.exception_kind,
                                    "reason": command.reason,
                                },
                            )
                        ).scalar_one(),
                    )
                else:
                    row = (
                        await session.execute(
                            text(
                                """
                                UPDATE request_engine.schedule_exceptions
                                   SET during = tstzrange(:start_at, :end_at, '[)'),
                                       exception_kind = :exception_kind,
                                       reason = :reason
                                 WHERE organization_id = :organization_id
                                   AND id = :exception_id
                                   AND resource_id = :resource_id
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                                "exception_id": command.exception_id,
                                "start_at": start_at,
                                "end_at": end_at,
                                "exception_kind": command.exception_kind,
                                "reason": command.reason,
                            },
                        )
                    ).first()
                    if row is None:
                        raise ContextualConfigurationConflict(
                            "schedule exception is missing or belongs to another Resource"
                        )
                    exception_id = command.exception_id

                final_revision = cast(
                    int,
                    (
                        await session.execute(
                            text(
                                """
                                SELECT availability_revision
                                FROM request_engine.resources
                                WHERE organization_id = :organization_id
                                  AND id = :resource_id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                            },
                        )
                    ).scalar_one(),
                )
                state = ResourceScheduleExceptionState(
                    exception_id=exception_id,
                    resource_id=command.resource_id,
                    start_at=start_at,
                    end_at=end_at,
                    exception_kind=command.exception_kind,
                    reason=command.reason,
                    resource_availability_revision=final_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.set_resource_schedule_exception",
                    aggregate_kind="ResourceScheduleException",
                    aggregate_id=exception_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "resource_id": str(command.resource_id),
                        "exception_kind": command.exception_kind,
                        "previous_resource_availability_revision": current_revision,
                        "new_resource_availability_revision": final_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"exception": _state_to_json(state)},
                )
                return state
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"23P01", "23514", "55000"}:
                raise ContextualConfigurationConflict(
                    "Resource-wide schedule exception conflicts with authoritative state"
                ) from None
            raise


def _state_to_json(state: ResourceScheduleExceptionState) -> dict[str, object]:
    return {
        "exception_id": str(state.exception_id),
        "resource_id": str(state.resource_id),
        "start_at": state.start_at.isoformat(),
        "end_at": state.end_at.isoformat(),
        "exception_kind": state.exception_kind,
        "reason": state.reason,
        "resource_availability_revision": state.resource_availability_revision,
    }


def _state_from_json(value: dict[str, object]) -> ResourceScheduleExceptionState:
    kind = cast(str, value["exception_kind"])
    if kind not in ("available", "unavailable"):
        raise ValueError("stored exception_kind is invalid")
    return ResourceScheduleExceptionState(
        exception_id=UUID(cast(str, value["exception_id"])),
        resource_id=UUID(cast(str, value["resource_id"])),
        start_at=datetime.fromisoformat(cast(str, value["start_at"])),
        end_at=datetime.fromisoformat(cast(str, value["end_at"])),
        exception_kind=kind,
        reason=cast(str | None, value.get("reason")),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )
