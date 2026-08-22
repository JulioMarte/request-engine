from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from request_engine.modules.discovery.adapters.db import (
    publication_codec,
    publication_scope,
    publication_store,
)
from request_engine.modules.discovery.application.commands.publication import (
    DiscoveryPublicationState,
    PublishDiscoverySupplyCommand,
)
from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_DISCOVERY_SCOPE,
    require_operational_authority,
)


class PostgresDiscoveryPublishCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def publish(self, command: PublishDiscoverySupplyCommand) -> DiscoveryPublicationState:
        start, end, visibility = _validated(command)
        fingerprint = command_fingerprint(
            "discovery.publish_supply",
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "location_id": command.location_id,
                "resource_id": command.resource_id,
                "effective_start": start,
                "effective_end": end,
                "provider_visibility": visibility,
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idem_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="discovery.publish_supply",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return publication_codec.state_from_json(
                        cast(dict[str, object], replay["state"])
                    )
                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_DISCOVERY_SCOPE,
                )
                if not await publication_scope.validate_scope(
                    session,
                    organization_id=command.organization_id,
                    offering_id=command.offering_id,
                    location_id=command.location_id,
                    resource_id=command.resource_id,
                    effective_start=start,
                    effective_end=end,
                ):
                    raise DiscoveryConfigurationConflict(
                        "discovery publication scope unavailable"
                    )
                row = await publication_store.insert_publication(
                    session,
                    organization_id=command.organization_id,
                    offering_id=command.offering_id,
                    location_id=command.location_id,
                    resource_id=command.resource_id,
                    effective_start=start,
                    effective_end=end,
                    provider_visibility=visibility,
                )
                state = DiscoveryPublicationState(
                    id=cast(UUID, row["id"]),
                    offering_id=command.offering_id,
                    location_id=command.location_id,
                    resource_id=command.resource_id,
                    effective_start=start,
                    effective_end=end,
                    provider_visibility=visibility,
                    status="active",
                    revision=cast(int, row["revision"]),
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="discovery.publish_supply",
                    aggregate_kind="DiscoveryPublication",
                    aggregate_id=state.id,
                    idempotency_id=idem_id,
                    details={"authority": authority.audit_details()},
                )
                await complete_idempotency(
                    session, idem_id, {"state": publication_codec.state_to_json(state)}
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise DiscoveryConfigurationConflict(
                    "discovery publication overlaps existing effective publication"
                ) from None
            raise


def _validated(
    command: PublishDiscoverySupplyCommand,
) -> tuple[datetime, datetime | None, str]:
    start = command.effective_start
    end = command.effective_end
    if start.tzinfo is None or (end is not None and end.tzinfo is None):
        raise ValueError("discovery publication dates must be timezone-aware")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC) if end is not None else None
    if end is not None and end <= start:
        raise ValueError("effective_end must be after effective_start")
    visibility = command.provider_visibility.strip().lower()
    if visibility not in {"hidden", "public"}:
        raise ValueError("provider_visibility must be hidden or public")
    return start, end, visibility
