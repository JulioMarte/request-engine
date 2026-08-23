from typing import Literal

import pytest

from request_engine.entrypoints.http.discovery_app import create_discovery_app
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.platform.security.platform_discovery import PlatformDiscoveryActor


class LocalSlots:
    async def find_published_slots(self, query: PublishedSlotQuery) -> tuple[object, ...]:
        del query
        return ()


class RemoteSlots(LocalSlots):
    trust_boundary: Literal["remote"] = "remote"


class Candidates:
    async def find_candidates(self, query: object, *, scan_limit: int) -> tuple[object, ...]:
        del query, scan_limit
        return ()


class Handoffs:
    async def issue_handoff(self, candidate: object, slot: object) -> str | None:
        del candidate, slot
        return None


class Actors:
    async def resolve_actor(self, request: object) -> PlatformDiscoveryActor:
        del request
        raise AssertionError("not used during composition")


def test_public_discovery_rejects_local_booking_reader() -> None:
    with pytest.raises((AttributeError, RuntimeError)):
        create_discovery_app(
            candidate_reader=Candidates(),  # type: ignore[arg-type]
            slot_reader=LocalSlots(),  # type: ignore[arg-type]
            handoff_issuer=Handoffs(),  # type: ignore[arg-type]
            actor_resolver=Actors(),  # type: ignore[arg-type]
        )


def test_public_discovery_accepts_remote_booking_boundary() -> None:
    app = create_discovery_app(
        candidate_reader=Candidates(),  # type: ignore[arg-type]
        slot_reader=RemoteSlots(),  # type: ignore[arg-type]
        handoff_issuer=Handoffs(),  # type: ignore[arg-type]
        actor_resolver=Actors(),  # type: ignore[arg-type]
    )
    assert app.title == "Request Engine Discovery"
