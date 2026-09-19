from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_actor_resolution import (
    PlatformPrincipalActorResolver,
    PlatformPrincipalResolutionUnavailable,
)
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthoritySnapshot,
)


class StubPlatformAuthorityReader:
    def __init__(
        self,
        snapshot: PrincipalAuthoritySnapshot | None = None,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.requested_principal_id: UUID | None = None

    async def read_platform_principal_authority(
        self, *, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        self.requested_principal_id = principal_id
        if self.error is not None:
            raise self.error
        return self.snapshot


def _snapshot(principal_id: UUID, *, principal_kind: str = "human") -> PrincipalAuthoritySnapshot:
    return PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind=principal_kind,
        authority_revision=5,
        capabilities=frozenset({"organization.provision"}),
        delegable_capabilities=frozenset({"organization.provision"}),
    )


@pytest.mark.asyncio
async def test_platform_actor_comes_only_from_persisted_authority_snapshot() -> None:
    principal_id = uuid4()
    reader = StubPlatformAuthorityReader(_snapshot(principal_id))
    resolver = PlatformPrincipalActorResolver(reader)

    actor = await resolver.resolve_platform_actor(
        principal_id=principal_id,
        authentication_method="re_native_session",
        credential_id="session:7",
        interaction_id="interaction-9",
    )

    assert actor is not None
    assert reader.requested_principal_id == principal_id
    assert actor.principal_id == principal_id
    assert actor.principal_kind is PrincipalKind.HUMAN
    assert actor.capabilities == frozenset({"organization.provision"})
    assert actor.authority_revision == 5
    assert actor.authentication_method == "re_native_session"
    assert actor.credential_id == "session:7"
    assert actor.interaction_id == "interaction-9"
    assert not hasattr(actor, "organization_id")


@pytest.mark.asyncio
async def test_missing_or_inactive_platform_principal_resolves_to_no_actor() -> None:
    resolver = PlatformPrincipalActorResolver(StubPlatformAuthorityReader(None))

    assert (
        await resolver.resolve_platform_actor(
            principal_id=uuid4(), authentication_method="re_native_session"
        )
        is None
    )


@pytest.mark.asyncio
async def test_legacy_principal_kind_fails_closed_in_platform_resolution() -> None:
    principal_id = uuid4()
    resolver = PlatformPrincipalActorResolver(
        StubPlatformAuthorityReader(_snapshot(principal_id, principal_kind="service"))
    )

    with pytest.raises(PlatformPrincipalResolutionUnavailable):
        await resolver.resolve_platform_actor(
            principal_id=principal_id, authentication_method="workload_identity"
        )


@pytest.mark.asyncio
async def test_authority_materialization_failure_never_degrades_to_empty_actor() -> None:
    resolver = PlatformPrincipalActorResolver(
        StubPlatformAuthorityReader(error=PrincipalAuthorityMaterializationError("drift"))
    )

    with pytest.raises(PlatformPrincipalResolutionUnavailable):
        await resolver.resolve_platform_actor(
            principal_id=uuid4(), authentication_method="re_native_session"
        )
