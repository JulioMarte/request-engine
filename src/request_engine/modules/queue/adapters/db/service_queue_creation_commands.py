from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.queue.application.commands.create_service_queue import (
    CreateServiceQueueCommand,
    ServiceQueueBootstrapState,
)
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

_CAPABILITY = "queue.create_service_queue"


class PostgresServiceQueueCreationCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_service_queue(
        self, command: CreateServiceQueueCommand
    ) -> ServiceQueueBootstrapState:
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "location_id": command.location_id,
                "offering_id": command.offering_id,
                "queue_key": command.queue_key.strip(),
                "display_name": command.display_name.strip(),
            },
        )
        try:
            async with tenant_transaction(self._session_factory, command.organization_id) as session:
                idem, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(cast(dict[str, object], replay["service_queue"]))
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                location = (
                    await session.execute(
                        text(
                            """
                            SELECT 1 FROM request_engine.locations
                            WHERE organization_id = :organization_id
                              AND id = :location_id AND active
                            """
                        ),
                        {"organization_id": command.organization_id, "location_id": command.location_id},
                    )
                ).first()
                if location is None:
                    raise ValueError("location_id is missing, inactive, or foreign")
                if command.offering_id is not None:
                    offering = (
                        await session.execute(
                            text(
                                """
                                SELECT 1 FROM request_engine.offerings
                                WHERE organization_id = :organization_id
                                  AND id = :offering_id
                                """
                            ),
                            {"organization_id": command.organization_id, "offering_id": command.offering_id},
                        )
                    ).first()
                    if offering is None:
                        raise ValueError("offering_id is missing or foreign")
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.service_queues (
                                    organization_id, location_id, offering_id, queue_key, display_name
                                ) VALUES (
                                    :organization_id, :location_id, :offering_id, :queue_key, :display_name
                                )
                                RETURNING id, queue_key, display_name, location_id, offering_id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "location_id": command.location_id,
                                "offering_id": command.offering_id,
                                "queue_key": command.queue_key.strip(),
                                "display_name": command.display_name.strip(),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = ServiceQueueBootstrapState(
                    queue_id=cast(UUID, row["id"]),
                    queue_key=cast(str, row["queue_key"]),
                    display_name=cast(str, row["display_name"]),
                    location_id=cast(UUID, row["location_id"]),
                    offering_id=cast(UUID | None, row["offering_id"]),
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="ServiceQueue",
                    aggregate_id=state.queue_id,
                    idempotency_id=idem,
                    details={"authority": authority.audit_details(), "queue_key": state.queue_key},
                )
                await complete_idempotency(
                    session, idem, {"service_queue": _state_to_json(state)}
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise ValueError("queue_key already exists in this tenant") from None
            raise


def _state_to_json(state: ServiceQueueBootstrapState) -> dict[str, object]:
    return {
        "queue_id": str(state.queue_id),
        "queue_key": state.queue_key,
        "display_name": state.display_name,
        "location_id": str(state.location_id),
        "offering_id": str(state.offering_id) if state.offering_id else None,
    }


def _state_from_json(value: dict[str, object]) -> ServiceQueueBootstrapState:
    offering_id = value.get("offering_id")
    return ServiceQueueBootstrapState(
        queue_id=UUID(cast(str, value["queue_id"])),
        queue_key=cast(str, value["queue_key"]),
        display_name=cast(str, value["display_name"]),
        location_id=UUID(cast(str, value["location_id"])),
        offering_id=UUID(cast(str, offering_id)) if offering_id is not None else None,
    )
