from __future__ import annotations

from typing import cast

from sqlalchemy.exc import DBAPIError

from request_engine.modules.booking.adapters.db import (
    resource_schedule_exception_audit as audit,
)
from request_engine.modules.booking.adapters.db import (
    resource_schedule_exception_codec as codec,
)
from request_engine.modules.booking.adapters.db import resource_schedule_exception_store as store
from request_engine.modules.booking.application.commands.set_resource_schedule_exception import (
    ResourceScheduleExceptionState,
    SetResourceScheduleExceptionCommand,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
)
from request_engine.modules.booking.domain.availability import require_aware_utc
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
            codec.command_payload(command, start_at=start_at, end_at=end_at),
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
                    return codec.from_json(cast(dict[str, object], replay["exception"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                current_revision = await store.require_resource_revision(
                    session,
                    organization_id=command.organization_id,
                    resource_id=command.resource_id,
                    expected_revision=command.expected_resource_availability_revision,
                )
                exception_id = await store.upsert_exception(
                    session,
                    organization_id=command.organization_id,
                    resource_id=command.resource_id,
                    exception_id=command.exception_id,
                    start_at=start_at,
                    end_at=end_at,
                    exception_kind=command.exception_kind,
                    reason=command.reason,
                )
                final_revision = await store.availability_revision(
                    session,
                    organization_id=command.organization_id,
                    resource_id=command.resource_id,
                )
                state = codec.make_state(
                    command,
                    exception_id=exception_id,
                    start_at=start_at,
                    end_at=end_at,
                    resource_availability_revision=final_revision,
                )
                await audit.append_resource_exception_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    exception_id=exception_id,
                    resource_id=command.resource_id,
                    exception_kind=command.exception_kind,
                    idempotency_id=idempotency_id,
                    authority=authority,
                    previous_revision=current_revision,
                    new_revision=final_revision,
                )
                await complete_idempotency(
                    session, idempotency_id, {"exception": codec.to_json(state)}
                )
                return state
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"23P01", "23514", "55000"}:
                raise ContextualConfigurationConflict(
                    "Resource-wide schedule exception conflicts with authoritative state"
                ) from None
            raise
