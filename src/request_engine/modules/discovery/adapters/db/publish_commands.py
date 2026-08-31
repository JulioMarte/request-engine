from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.discovery.adapters.db import (
    publication_codec,
    publication_scope,
    publication_state,
    publication_store,
)
from request_engine.modules.discovery.adapters.db.publication_validation import (
    validated_publication_intent,
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
        start, end, visibility, start_origin = validated_publication_intent(command)
        fingerprint_start: object = start if start_origin == "explicit" else start_origin
        fingerprint = command_fingerprint(
            "discovery.publish_supply",
            {
                "authority_party_id": command.authority_party_id,
                "offering_id": command.offering_id,
                "location_id": command.location_id,
                "resource_id": command.resource_id,
                "effective_start": fingerprint_start,
                "effective_start_origin": start_origin,
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
                    raise DiscoveryConfigurationConflict("discovery publication scope unavailable")
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
                state = publication_state.created_state(
                    row,
                    command,
                    effective_start=start,
                    effective_end=end,
                    provider_visibility=visibility,
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
