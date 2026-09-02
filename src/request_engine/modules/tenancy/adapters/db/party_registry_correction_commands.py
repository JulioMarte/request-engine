"""PostgreSQL `parties.rename` and `parties.add_document` command adapters."""

from typing import Never
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_correction_records import finish_party_state
from request_engine.modules.tenancy.adapters.db.party_correction_support import run_correction
from request_engine.modules.tenancy.adapters.db.party_registry_conflicts import (
    raise_added_document_conflict,
)
from request_engine.modules.tenancy.adapters.db.party_registry_correction_codec import (
    replay_document,
    replay_party,
)
from request_engine.modules.tenancy.adapters.db.party_registry_rows import single_document_row
from request_engine.modules.tenancy.adapters.db.party_registry_store import insert_documents, lock_party
from request_engine.modules.tenancy.adapters.db.party_registry_views import document_by_id
from request_engine.modules.tenancy.application.commands import add_party_document, rename_party
from request_engine.modules.tenancy.application.errors import PartyNotFound
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyDocumentInput,
    PartyIdentityDocument,
    RegisteredParty,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.postgres import command_fingerprint

_RENAME_CAPABILITY = "parties.rename"
_ADD_DOCUMENT_CAPABILITY = "parties.add_document"
_RENAME_PARTY_SQL = text(
    "UPDATE request_engine.parties SET display_name = :display_name, "
    "updated_at = clock_timestamp() WHERE organization_id = :organization_id AND id = :party_id"
)


class PostgresPartyCorrectionCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def rename_party(self, command: rename_party.RenamePartyCommand) -> RegisteredParty:
        fingerprint = command_fingerprint(
            _RENAME_CAPABILITY,
            {"party_id": command.party_id, "display_name": command.display_name},
        )

        async def mutate(session: AsyncSession, idempotency_id: UUID) -> RegisteredParty:
            await lock_party(session, command.organization_id, command.party_id)
            await session.execute(
                _RENAME_PARTY_SQL,
                {
                    "organization_id": command.organization_id,
                    "party_id": command.party_id,
                    "display_name": command.display_name,
                },
            )
            return await finish_party_state(
                session,
                command,
                _RENAME_CAPABILITY,
                idempotency_id,
                {"display_name": command.display_name},
            )

        return await run_correction(
            self._session_factory, command, _RENAME_CAPABILITY, fingerprint, replay_party, mutate
        )

    async def add_party_document(
        self, command: add_party_document.AddPartyDocumentCommand
    ) -> PartyIdentityDocument:
        authority = command.authority or ""
        document = PartyDocumentInput(command.kind, command.value, command.authority)
        fingerprint = command_fingerprint(
            _ADD_DOCUMENT_CAPABILITY,
            {
                "party_id": command.party_id,
                "kind": command.kind,
                "authority": command.authority,
                "value": command.value,
            },
        )

        async def mutate(session: AsyncSession, idempotency_id: UUID) -> PartyIdentityDocument:
            await lock_party(session, command.organization_id, command.party_id)
            inserted = await insert_documents(session, single_document_row(command))
            state = await finish_party_state(
                session,
                command,
                _ADD_DOCUMENT_CAPABILITY,
                idempotency_id,
                {
                    "kind": command.kind,
                    "authority": command.authority,
                    "normalized_value": command.value,
                },
            )
            added = document_by_id(state, UUID(str(inserted[0]["id"])))
            if added is None:
                raise PartyNotFound(command.party_id)
            return added

        async def on_conflict(exc: IntegrityError) -> Never:
            await raise_added_document_conflict(
                self._session_factory,
                command.organization_id,
                command.party_id,
                document,
                exc,
            )

        return await run_correction(
            self._session_factory,
            command,
            _ADD_DOCUMENT_CAPABILITY,
            fingerprint,
            lambda data: replay_document(
                data, command.kind, authority, command.value, command.party_id
            ),
            mutate,
            on_conflict,
        )
