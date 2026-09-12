from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.identity_resolution import (
    IdentityBindingPlane,
    IdentityBindingSnapshot,
    IdentityBindingStatus,
    IdentityPrincipalResolver,
    IdentitySubjectClassMismatch,
)
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_http import NativeSessionHttpActorResolver
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
    NativeSessionAuthenticator,
    NativeSessionEvidence,
    NativeSessionSnapshot,
    NativeSessionStatus,
)
from request_engine.platform.security.principal_authority import PrincipalAuthoritySnapshot

pytestmark = [pytest.mark.unit, pytest.mark.security]
NOW = datetime(2026, 9, 8, tzinfo=UTC)


class BindingReader:
    def __init__(self, binding: IdentityBindingSnapshot) -> None:
        self.binding = binding

    async def read_tenant_subject_bindings(
        self,
        *,
        identity_authority_id: UUID,
        subject_id: str,
        organization_id: UUID,
    ) -> tuple[IdentityBindingSnapshot, ...]:
        binding = self.binding
        if (
            binding.identity_authority_id == identity_authority_id
            and binding.subject_id == subject_id
            and binding.organization_id == organization_id
        ):
            return (binding,)
        return ()

    async def read_platform_subject_bindings(
        self, *, identity_authority_id: UUID, subject_id: str
    ) -> tuple[IdentityBindingSnapshot, ...]:
        return ()


class TenantAuthorityReader:
    def __init__(self, snapshot: PrincipalAuthoritySnapshot) -> None:
        self.snapshot = snapshot

    async def read_tenant_principal_authority(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        if principal_id == self.snapshot.principal_id:
            return self.snapshot
        return None


class PlatformAuthorityReader:
    async def read_platform_principal_authority(
        self, *, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        return None


class SessionReader:
    def __init__(self, snapshot: NativeSessionSnapshot) -> None:
        self.snapshot = snapshot

    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None:
        if session_id == self.snapshot.session_id:
            return self.snapshot
        return None


def _binding(
    authority_id: UUID, subject_id: str, organization_id: UUID, principal_id: UUID
) -> IdentityBindingSnapshot:
    return IdentityBindingSnapshot(
        binding_id=uuid4(),
        identity_authority_id=authority_id,
        subject_id=subject_id,
        principal_id=principal_id,
        principal_plane=IdentityBindingPlane.TENANT,
        organization_id=organization_id,
        status=IdentityBindingStatus.ACTIVE,
        revision=1,
    )


def _authority(principal_id: UUID, kind: str) -> PrincipalAuthoritySnapshot:
    return PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind=kind,
        authority_revision=9,
        capabilities=frozenset({"booking.read"}),
        delegable_capabilities=frozenset(),
    )


def test_raw_tokens_and_parsed_secrets_are_redacted_from_repr() -> None:
    token = issue_opaque_token()
    from request_engine.platform.security.native_auth import parse_opaque_token

    parsed = parse_opaque_token(token.raw_token)
    evidence = NativeSessionEvidence(token.raw_token)

    assert token.raw_token not in repr(token)
    assert parsed.secret not in repr(parsed)
    assert token.raw_token not in repr(evidence)


@pytest.mark.asyncio
async def test_human_authentication_cannot_activate_agent_principal() -> None:
    authority_id = uuid4()
    organization_id = uuid4()
    principal_id = uuid4()
    subject_id = "human-subject"
    resolver = IdentityPrincipalResolver(
        binding_reader=BindingReader(
            _binding(authority_id, subject_id, organization_id, principal_id)
        ),
        tenant_authority_reader=TenantAuthorityReader(_authority(principal_id, "agent")),
        platform_authority_reader=PlatformAuthorityReader(),
    )

    with pytest.raises(IdentitySubjectClassMismatch):
        await resolver.resolve_tenant_actor(
            subject=AuthenticatedSubject(
                authority_id=str(authority_id),
                subject_id=subject_id,
                subject_class=AuthenticatedSubjectClass.HUMAN,
            ),
            organization_id=organization_id,
            authentication_method="native_session",
        )


@pytest.mark.asyncio
async def test_http_native_resolver_reloads_current_authority_for_selected_tenant() -> None:
    token = issue_opaque_token()
    authority_id = uuid4()
    organization_id = uuid4()
    principal_id = uuid4()
    native_identity_id = uuid4()
    session = NativeSessionSnapshot(
        session_id=token.token_id,
        native_identity_id=native_identity_id,
        identity_authority_id=authority_id,
        credential_id=uuid4(),
        token_digest=token.digest,
        session_epoch=1,
        current_session_epoch=1,
        session_status=NativeSessionStatus.ACTIVE,
        identity_status=NativeIdentityStatus.ACTIVE,
        credential_status=NativeCredentialStatus.ACTIVE,
        expires_at=NOW + timedelta(hours=1),
    )
    principal_resolver = IdentityPrincipalResolver(
        binding_reader=BindingReader(
            _binding(authority_id, str(native_identity_id), organization_id, principal_id)
        ),
        tenant_authority_reader=TenantAuthorityReader(_authority(principal_id, "human")),
        platform_authority_reader=PlatformAuthorityReader(),
    )
    resolver = NativeSessionHttpActorResolver(
        authenticator=NativeSessionAuthenticator(
            session_reader=SessionReader(session), clock=lambda: NOW
        ),
        principal_resolver=principal_resolver,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/example",
            "headers": [
                (b"authorization", f"Bearer {token.raw_token}".encode()),
                (b"x-re-organization-id", str(organization_id).encode()),
                (b"x-re-principal-id", str(uuid4()).encode()),
            ],
        }
    )

    actor = await resolver.resolve_actor(request)

    assert actor.organization_id == organization_id
    assert actor.principal_id == principal_id
    assert actor.authority_revision == 9
    assert actor.credential_id == str(token.token_id)
