from typing import cast
from uuid import UUID

from request_engine.modules.discovery.adapters.db import (
    publication_codec,
    publication_store,
)
from request_engine.modules.discovery.application.commands.publication import (
    DiscoveryPublicationState,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.discovery.application.errors import (
    DiscoveryConfigurationConflict,
    DiscoveryRevisionConflict,
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


class PostgresDiscoveryRevokeCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def revoke(
        self, command: RevokeDiscoveryPublicationCommand
    ) -> DiscoveryPublicationState:
        fingerprint = command_fingerprint(
            "discovery.revoke_publication",
            {
                "authority_party_id": command.authority_party_id,
                "publication_id": command.publication_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(
            self._session_factory, command.organization_id
        ) as session:
            idem_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="discovery.revoke_publication",
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
            current = await publication_store.lock_publication(
                session, command.organization_id, command.publication_id
            )
            if current is None or current["status"] != "active":
                raise DiscoveryConfigurationConflict("discovery publication unavailable")
            actual = cast(int, current["revision"])
            if actual != command.expected_revision:
                raise DiscoveryRevisionConflict(
                    command.publication_id,
                    command.expected_revision,
                    actual,
                )
            updated = await publication_store.revoke_publication(
                session, command.organization_id, command.publication_id
            )
            state = DiscoveryPublicationState(
                id=command.publication_id,
                offering_id=cast(UUID, current["offering_id"]),
                location_id=cast(UUID, current["location_id"]),
                resource_id=cast(UUID | None, current["resource_id"]),
                effective_start=current["effective_start"],
                effective_end=current["effective_end"],
                provider_visibility=cast(str, current["provider_visibility"]),
                status="revoked",
                revision=cast(int, updated["revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="discovery.revoke_publication",
                aggregate_kind="DiscoveryPublication",
                aggregate_id=state.id,
                idempotency_id=idem_id,
                details={"authority": authority.audit_details(), "previous_revision": actual},
            )
            await complete_idempotency(
                session, idem_id, {"state": publication_codec.state_to_json(state)}
            )
            return state
