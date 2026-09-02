"""PostgreSQL `parties.register` command adapter (idempotent, one transaction)."""

from typing import cast

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db.party_registration_write import (
    write_registered_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_codec import (
    party_from_json,
    party_to_json,
)
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import (
    raise_document_conflict,
)
from request_engine.modules.tenancy.adapters.db.party_registry_fingerprints import (
    register_fingerprint,
)
from request_engine.modules.tenancy.application.commands import register_party
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_REGISTER_PARTY_CAPABILITY = "parties.register"


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
                state = await write_registered_party(
                    session,
                    command,
                    command_name=_REGISTER_PARTY_CAPABILITY,
                    idempotency_id=idempotency_id,
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"party": party_to_json(state)},
                )
                return state
        except IntegrityError as exc:
            await raise_document_conflict(
                self._session_factory,
                command.organization_id,
                command.documents,
                exc,
            )
