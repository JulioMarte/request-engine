from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.identity_resolution import (
    IdentityBindingPlane,
    IdentityBindingReader,
    IdentityBindingSnapshot,
    IdentityBindingStatus,
    IdentityBindingSuspended,
    IdentityPrincipalResolver,
    TenantContextAmbiguous,
    TenantContextRequired,
)
from request_engine.platform.security.principal_authority import PrincipalAuthoritySnapshot

pytestmark = [pytest.mark.unit, pytest.mark.security]


class FakeBindingReader(IdentityBindingReader):
    def __init__(self, bindings: tuple[IdentityBindingSnapshot, ...]) -> None:
        self.bindings = bindings

    async def read_subject_bindings(
        self, *, identity_authority_id: UUID, subject_id: str
    ) -> tuple[IdentityBindingSnapshot, ...]:
        return tuple(
            binding
            for binding in self.bindings
            if binding.identity_authority_id == identity_authority_id
            and binding.subject_id == subject_id
        )


class FakeTenantAuthorityReader:
    def __init__(self, snapshots: dict[UUID, PrincipalAuthoritySnapshot]) -> None:
        self.snapshots = snapshots

    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        return self.snapshots.get(principal_id)


class FakePlatformAuthorityReader:
    async def read_platform_principal_authority(
        self, *, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        return None


def _subject(authority_id: UUID, subject_id: str = "native-user") -> AuthenticatedSubject:
    return AuthenticatedSubject(
        authority_id=str(authority_id),
        subject_id=subject_id,
        subject_class=AuthenticatedSubjectClass.HUMAN,
    )


def _binding(
    *,
    authority_id: UUID,
    organization_id: UUID,
    principal_id: UUID,
    status: IdentityBindingStatus = IdentityBindingStatus.ACTIVE,
) -> IdentityBindingSnapshot:
    return IdentityBindingSnapshot(
        binding_id=uuid4(),
        identity_authority_id=authority_id,
        subject_id="native-user",
        principal_id=principal_id,
        principal_plane=IdentityBindingPlane.TENANT,
        organization_id=organization_id,
        status=status,
        revision=1,
    )


def _authority(principal_id: UUID, revision: int = 7) -> PrincipalAuthoritySnapshot:
    return PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind="human",
        authority_revision=revision,
        capabilities=frozenset({"booking.read", "booking.create"}),
        delegable_capabilities=frozenset(),
    )


@pytest.mark.asyncio
async def test_tenant_context_is_mandatory() -> None:
    resolver = IdentityPrincipalResolver(
        binding_reader=FakeBindingReader(()),
        tenant_authority_reader=FakeTenantAuthorityReader({}),
        platform_authority_reader=FakePlatformAuthorityReader(),
    )

    with pytest.raises(TenantContextRequired):
        await resolver.resolve_tenant_actor(
            subject=_subject(uuid4()),
            organization_id=None,
            authentication_method="native_session",
        )


@pytest.mark.asyncio
async def test_binding_selects_principal_but_authority_comes_from_current_snapshot() -> None:
    authority_id = uuid4()
    organization_id = uuid4()
    principal_id = uuid4()
    binding = _binding(
        authority_id=authority_id,
        organization_id=organization_id,
        principal_id=principal_id,
    )
    resolver = IdentityPrincipalResolver(
        binding_reader=FakeBindingReader((binding,)),
        tenant_authority_reader=FakeTenantAuthorityReader(
            {principal_id: _authority(principal_id, revision=11)}
        ),
        platform_authority_reader=FakePlatformAuthorityReader(),
    )

    actor = await resolver.resolve_tenant_actor(
        subject=_subject(authority_id),
        organization_id=organization_id,
        authentication_method="native_session",
        credential_id="session:abc",
    )

    assert actor.principal_id == principal_id
    assert actor.organization_id == organization_id
    assert actor.authority_revision == 11
    assert actor.capabilities == frozenset({"booking.read", "booking.create"})


@pytest.mark.asyncio
async def test_suspended_binding_denies_even_when_principal_has_authority() -> None:
    authority_id = uuid4()
    organization_id = uuid4()
    principal_id = uuid4()
    binding = _binding(
        authority_id=authority_id,
        organization_id=organization_id,
        principal_id=principal_id,
        status=IdentityBindingStatus.SUSPENDED,
    )
    resolver = IdentityPrincipalResolver(
        binding_reader=FakeBindingReader((binding,)),
        tenant_authority_reader=FakeTenantAuthorityReader({principal_id: _authority(principal_id)}),
        platform_authority_reader=FakePlatformAuthorityReader(),
    )

    with pytest.raises(IdentityBindingSuspended):
        await resolver.resolve_tenant_actor(
            subject=_subject(authority_id),
            organization_id=organization_id,
            authentication_method="native_session",
        )


@pytest.mark.asyncio
async def test_duplicate_active_binding_fails_closed() -> None:
    authority_id = uuid4()
    organization_id = uuid4()
    first_principal = uuid4()
    second_principal = uuid4()
    bindings = (
        _binding(
            authority_id=authority_id,
            organization_id=organization_id,
            principal_id=first_principal,
        ),
        _binding(
            authority_id=authority_id,
            organization_id=organization_id,
            principal_id=second_principal,
        ),
    )
    resolver = IdentityPrincipalResolver(
        binding_reader=FakeBindingReader(bindings),
        tenant_authority_reader=FakeTenantAuthorityReader({}),
        platform_authority_reader=FakePlatformAuthorityReader(),
    )

    with pytest.raises(TenantContextAmbiguous):
        await resolver.resolve_tenant_actor(
            subject=_subject(authority_id),
            organization_id=organization_id,
            authentication_method="native_session",
        )
