from uuid import UUID, uuid4

import pytest

from request_engine.entrypoints.http.operator_resolution import DeploymentOperatorActorResolver
from request_engine.platform.security.acting_operator import OperatorResolutionUnavailable
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthoritySnapshot,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _AuthorityReader:
    def __init__(self, snapshot: PrincipalAuthoritySnapshot | None) -> None:
        self.snapshot = snapshot

    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        return self.snapshot


class _FailingAuthorityReader:
    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        raise PrincipalAuthorityMaterializationError("unsafe persisted authority")


class _Ceiling:
    def __init__(self, capabilities: frozenset[str]) -> None:
        self.capabilities = capabilities

    async def operator_capabilities(
        self, organization_id: UUID, principal_id: UUID
    ) -> frozenset[str]:
        return self.capabilities


@pytest.mark.asyncio
async def test_re_owned_grants_are_authority_root_and_deployment_can_only_narrow() -> None:
    organization_id = uuid4()
    principal_id = uuid4()
    snapshot = PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind="human",
        authority_revision=9,
        capabilities=frozenset({"catalog.manage", "appointments.book"}),
        delegable_capabilities=frozenset({"catalog.manage"}),
    )
    resolver = DeploymentOperatorActorResolver(
        _AuthorityReader(snapshot),
        _Ceiling(frozenset({"catalog.manage", "platform.identity.recover"})),
    )

    actor = await resolver.resolve_operator_actor(organization_id, principal_id)

    assert actor is not None
    assert actor.capabilities == frozenset({"catalog.manage"})
    assert actor.authority_revision == 9


@pytest.mark.asyncio
async def test_absent_deployment_ceiling_does_not_remove_re_owned_authority() -> None:
    principal_id = uuid4()
    snapshot = PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind="human",
        authority_revision=3,
        capabilities=frozenset({"appointments.book"}),
        delegable_capabilities=frozenset(),
    )
    resolver = DeploymentOperatorActorResolver(_AuthorityReader(snapshot))

    actor = await resolver.resolve_operator_actor(uuid4(), principal_id)

    assert actor is not None
    assert actor.capabilities == frozenset({"appointments.book"})


@pytest.mark.asyncio
async def test_unsafe_persisted_authority_fails_closed() -> None:
    resolver = DeploymentOperatorActorResolver(_FailingAuthorityReader())

    with pytest.raises(OperatorResolutionUnavailable):
        await resolver.resolve_operator_actor(uuid4(), uuid4())
