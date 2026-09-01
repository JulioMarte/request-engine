"""PostgreSQL `parties.confirm_contact_point` command adapter (idempotent).

Uniform party-first locking: the party row is locked before the contact-point
row, matching the correction/rollback/deactivation paths so a concurrent
correction can never interleave the opposite lock order and deadlock.
"""

from typing import cast

from request_engine.modules.tenancy.adapters.db.party_registry_codec import (
    party_from_json,
    party_to_json,
)
from request_engine.modules.tenancy.adapters.db.party_registry_rows import audit_attribution
from request_engine.modules.tenancy.adapters.db.party_registry_store import (
    confirm_contact_point,
    lock_contact_point,
    lock_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_views import (
    contact_point_by_id,
    load_party_views,
)
from request_engine.modules.tenancy.adapters.db.party_revision_ledger import (
    record_party_revision,
)
from request_engine.modules.tenancy.application.commands import confirm_party_contact_point
from request_engine.modules.tenancy.application.errors import PartyContactPointNotFound
from request_engine.modules.tenancy.contracts.party_registry import PartyContactPoint
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CONFIRM_CAPABILITY = "parties.confirm_contact_point"


class PostgresPartyContactPointConfirmationCommands:
    """Operator-driven monotone verification of an unverified contact point."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def confirm_party_contact_point(
        self,
        command: confirm_party_contact_point.ConfirmPartyContactPointCommand,
    ) -> PartyContactPoint:
        fingerprint = command_fingerprint(
            _CONFIRM_CAPABILITY,
            {
                "party_id": str(command.party_id),
                "contact_point_id": str(command.contact_point_id),
            },
        )
        async with tenant_transaction(
            self._session_factory,
            command.organization_id,
        ) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CONFIRM_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                state = party_from_json(cast(dict[str, object], replay["party"]))
                affected = contact_point_by_id(state, command.contact_point_id)
                if affected is None:
                    raise PartyContactPointNotFound(command.party_id, command.contact_point_id)
                return affected
            await lock_party(session, command.organization_id, command.party_id)
            locked = await lock_contact_point(
                session,
                command.organization_id,
                command.party_id,
                command.contact_point_id,
            )
            if locked is None:
                raise PartyContactPointNotFound(command.party_id, command.contact_point_id)
            already_verified = cast(bool, locked["verified"])
            if not already_verified:
                await confirm_contact_point(
                    session,
                    command.organization_id,
                    command.contact_point_id,
                )
                await record_party_revision(
                    session,
                    command=command,
                    organization_id=command.organization_id,
                    party_id=command.party_id,
                    change_kind="verification_flipped",
                )
            state = (await load_party_views(session, command.organization_id, [command.party_id]))[
                0
            ]
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CONFIRM_CAPABILITY,
                aggregate_kind="Party",
                aggregate_id=command.party_id,
                idempotency_id=idempotency_id,
                details={
                    "party_id": str(command.party_id),
                    "contact_point_id": str(command.contact_point_id),
                    "already_verified": already_verified,
                    **audit_attribution(command),
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"party": party_to_json(state)},
            )
            return cast(PartyContactPoint, contact_point_by_id(state, command.contact_point_id))
