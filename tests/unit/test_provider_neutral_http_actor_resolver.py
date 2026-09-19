from uuid import UUID, uuid4

import pytest
from fastapi import Request

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    ProviderNeutralHttpActorResolver,
)


class StaticSubjectResolver:
    def __init__(self, authenticated: AuthenticatedHttpSubject) -> None:
        self.authenticated = authenticated

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        del request
        return self.authenticated


class RecordingPrincipalResolver:
    def __init__(self, result: ActorContext) -> None:
        self.result = result
        self.subject: AuthenticatedSubject | None = None
        self.organization_id: UUID | None = None
        self.authentication_method: str | None = None
        self.credential_id: str | None = None

    async def resolve_tenant_actor(
        self,
        *,
        subject: AuthenticatedSubject,
        organization_id: UUID | None,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> ActorContext:
        del technical_principal_id, interaction_id
        self.subject = subject
        self.organization_id = organization_id
        self.authentication_method = authentication_method
        self.credential_id = credential_id
        return self.result


def _request(organization_id: UUID) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/capabilities",
            "headers": [
                (b"x-re-organization-id", str(organization_id).encode("ascii")),
            ],
        }
    )


@pytest.mark.asyncio
async def test_provider_neutral_http_resolver_materializes_authority_inside_re() -> None:
    organization_id = uuid4()
    authority_id = uuid4()
    subject = AuthenticatedSubject(
        authority_id=str(authority_id),
        subject_id="provider-subject",
        subject_class=AuthenticatedSubjectClass.HUMAN,
    )
    authenticated = AuthenticatedHttpSubject(
        subject=subject,
        authentication_method="oidc-test",
        credential_id="credential-7",
    )
    expected = ActorContext(
        organization_id=organization_id,
        principal_id=uuid4(),
        capabilities=frozenset({"staff.invite"}),
    )
    principal_resolver = RecordingPrincipalResolver(expected)
    resolver = ProviderNeutralHttpActorResolver(
        subject_resolver=StaticSubjectResolver(authenticated),
        principal_resolver=principal_resolver,
    )

    actual = await resolver.resolve_actor(_request(organization_id))

    assert actual is expected
    assert principal_resolver.subject is subject
    assert principal_resolver.organization_id == organization_id
    assert principal_resolver.authentication_method == "oidc-test"
    assert principal_resolver.credential_id == "credential-7"
