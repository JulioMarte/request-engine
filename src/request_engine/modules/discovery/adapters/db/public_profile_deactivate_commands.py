from typing import cast

from request_engine.modules.discovery.adapters.db.public_profile_deactivate_store import (
    deactivate_profile,
)
from request_engine.modules.discovery.adapters.db.public_profile_store import (
    lock_resource,
    state_from_json,
    state_to_json,
)
from request_engine.modules.discovery.application.commands.public_profile import (
    DeactivateResourcePublicProfileCommand,
    ResourcePublicProfileState,
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


class PostgresResourcePublicProfileDeactivateCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def deactivate_public_profile(
        self, command: DeactivateResourcePublicProfileCommand
    ) -> ResourcePublicProfileState:
        fingerprint = command_fingerprint(
            "discovery.deactivate_resource_public_profile",
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "expected_revision": command.expected_revision,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idem_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="discovery.deactivate_resource_public_profile",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return state_from_json(cast(dict[str, object], replay["state"]))
            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_DISCOVERY_SCOPE,
            )
            resource_key = await lock_resource(
                session, command.organization_id, command.resource_id
            )
            row = await deactivate_profile(
                session,
                organization_id=command.organization_id,
                resource_id=command.resource_id,
                expected_revision=command.expected_revision,
            )
            state = ResourcePublicProfileState(
                resource_id=command.resource_id,
                resource_key=resource_key,
                display_name=cast(str, row["display_name"]),
                role_label=cast(str | None, row["role_label"]),
                profile_image_ref=cast(str | None, row["profile_image_ref"]),
                active=cast(bool, row["active"]),
                revision=cast(int, row["revision"]),
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="discovery.deactivate_resource_public_profile",
                aggregate_kind="ResourcePublicProfile",
                aggregate_id=command.resource_id,
                idempotency_id=idem_id,
                details={"authority": authority.audit_details()},
            )
            await complete_idempotency(session, idem_id, {"state": state_to_json(state)})
            return state
