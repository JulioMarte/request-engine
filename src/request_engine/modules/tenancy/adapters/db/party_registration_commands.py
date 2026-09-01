"""PostgreSQL `parties.register` command adapter (idempotent, one transaction)."""

from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.party_registry_codec import (
    party_from_json,
    party_to_json,
)
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import (
    raise_document_conflict,
)
from request_engine.modules.tenancy.adapters.db.party_registry_rows import (
    contact_point_rows,
    document_rows,
)
from request_engine.modules.tenancy.adapters.db.party_registry_store import (
    insert_contact_points,
    insert_documents,
    insert_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_views import (
    load_party_views,
)
from request_engine.modules.tenancy.application.commands import register_party
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox

_REGISTER_PARTY_CAPABILITY = "parties.register"


def register_fingerprint(command: register_party.RegisterPartyCommand) -> dict[str, object]:
    return {
        "display_name": command.display_name,
        "registered_via": command.registered_via.value,
        "contact_points": [
            {"channel": c.channel, "normalized_value": c.value} for c in command.contact_points
        ],
        "documents": [{"kind": d.kind, "normalized_value": d.value} for d in command.documents],
    }


class PostgresPartyRegistrationCommands:
    """Tenancy-owned `parties.register` command with idempotent replay."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def register_party(
        self,
        command: register_party.RegisterPartyCommand,
    ) -> RegisteredParty:
        fingerprint = command_fingerprint(
            _REGISTER_PARTY_CAPABILITY,
            register_fingerprint(command),
        )
        try:
            async with tenant_transaction(
                self._session_factory,
                command.organization_id,
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_REGISTER_PARTY_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return party_from_json(cast(dict[str, object], replay["party"]))
                party_id = await insert_party(
                    session,
                    organization_id=command.organization_id,
                    display_name=command.display_name,
                    principal_id=command.principal_id,
                )
                await insert_contact_points(session, contact_point_rows(command, party_id))
                await insert_documents(session, document_rows(command, party_id))
                state = (await load_party_views(session, command.organization_id, [party_id]))[0]
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_REGISTER_PARTY_CAPABILITY,
                    aggregate_kind="Party",
                    aggregate_id=party_id,
                    idempotency_id=idempotency_id,
                    details={
                        "display_name": command.display_name,
                        "registered_via": command.registered_via.value,
                        "contact_point_count": len(state.contact_points),
                        "document_count": len(state.documents),
                    },
                )
                await append_outbox(
                    session,
                    organization_id=command.organization_id,
                    event_type="party.registered.v1",
                    aggregate_kind="Party",
                    aggregate_id=party_id,
                    payload={
                        "party_id": str(party_id),
                        "display_name": command.display_name,
                        "contact_point_count": len(state.contact_points),
                    },
                )
                await complete_idempotency(session, idempotency_id, {"party": party_to_json(state)})
                return state
        except IntegrityError as exc:
            await raise_document_conflict(
                self._session_factory, command.organization_id, command.documents, exc
            )
