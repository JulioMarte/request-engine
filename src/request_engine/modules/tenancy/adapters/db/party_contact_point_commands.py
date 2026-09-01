"""PostgreSQL party contact point command adapters (idempotent, one transaction)."""

from typing import cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.party_registry_codec import (
    party_from_json,
    party_to_json,
)
from request_engine.modules.tenancy.adapters.db.party_registry_rows import (
    single_contact_point_row,
)
from request_engine.modules.tenancy.adapters.db.party_registry_store import (
    insert_contact_points,
    lock_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_views import (
    contact_point_by_id,
    contact_point_by_value,
    load_party_views,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_contact_point,
)
from request_engine.modules.tenancy.application.errors import (
    PartyContactPointExists,
)
from request_engine.modules.tenancy.contracts.party_registry import PartyContactPoint
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_ADD_CAPABILITY = "parties.add_contact_point"
_CONFIRM_CAPABILITY = "parties.confirm_contact_point"


def add_fingerprint(
    command: add_party_contact_point.AddPartyContactPointCommand,
) -> dict[str, object]:
    return {
        "party_id": str(command.party_id),
        "channel": command.channel,
        "normalized_value": command.value,
        "registered_via": command.registered_via.value,
    }


class PostgresPartyContactPointCommands:
    """Tenancy-owned contact point commands with idempotent replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def add_party_contact_point(
        self,
        command: add_party_contact_point.AddPartyContactPointCommand,
    ) -> PartyContactPoint:
        fingerprint = command_fingerprint(_ADD_CAPABILITY, add_fingerprint(command))
        try:
            async with tenant_transaction(
                self._session_factory,
                command.organization_id,
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_ADD_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    state = party_from_json(cast(dict[str, object], replay["party"]))
                    return cast(
                        PartyContactPoint,
                        contact_point_by_value(state, command.channel, command.value),
                    )
                await lock_party(session, command.organization_id, command.party_id)
                inserted = await insert_contact_points(session, single_contact_point_row(command))
                contact_point_id = cast(UUID, inserted[0]["id"])
                state = (
                    await load_party_views(session, command.organization_id, [command.party_id])
                )[0]
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_ADD_CAPABILITY,
                    aggregate_kind="Party",
                    aggregate_id=command.party_id,
                    idempotency_id=idempotency_id,
                    details={
                        "party_id": str(command.party_id),
                        "contact_point_id": str(contact_point_id),
                        "channel": command.channel,
                        "normalized_value": command.value,
                        "registered_via": command.registered_via.value,
                        "verified": command.registered_via.value == "operator",
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"party": party_to_json(state)},
                )
                affected = contact_point_by_id(state, contact_point_id)
                return cast(PartyContactPoint, affected)
        except IntegrityError:
            raise PartyContactPointExists(
                command.party_id,
                command.channel,
                command.value,
            ) from None
