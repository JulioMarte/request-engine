"""`parties.read_revisions` application query: the identity revision ledger."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.tenancy.contracts.party_registry import PartyRevision


@dataclass(frozen=True, slots=True)
class PartyRevisionHistoryQuery:
    organization_id: UUID
    party_id: UUID


class PartyRevisionHistoryReader(Protocol):
    async def revision_history(
        self, query: PartyRevisionHistoryQuery
    ) -> tuple[PartyRevision, ...]: ...
