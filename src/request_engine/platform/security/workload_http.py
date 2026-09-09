from __future__ import annotations

from fastapi import Request

from request_engine.platform.security.native_http import bearer_token
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    HttpSubjectResolver,
)
from request_engine.platform.security.workload_auth import (
    WorkloadCredentialAuthenticator,
    WorkloadCredentialEvidence,
    WorkloadCredentialInvalid,
    WorkloadCredentialReader,
    parse_workload_token,
)

_WORKLOAD_AUTHENTICATION_METHOD = "workload_credential"


class WorkloadHttpSubjectResolver:
    """Authenticate a first-party workload bearer without materializing authority."""

    def __init__(self, authenticator: WorkloadCredentialAuthenticator) -> None:
        self._authenticator = authenticator

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        raw_token = bearer_token(request)
        parsed = parse_workload_token(raw_token)
        subject = await self._authenticator.authenticate(WorkloadCredentialEvidence(raw_token))
        return AuthenticatedHttpSubject(
            subject=subject,
            authentication_method=_WORKLOAD_AUTHENTICATION_METHOD,
            credential_id=str(parsed.credential_id),
        )


class DispatchedBearerSubjectResolver:
    """Dispatch one bearer token between human sessions and workload credentials.

    Native human sessions and workload credentials share the ``id.secret`` token
    shape, so dispatch is decided by RE-owned state: a token id that resolves to
    a persisted workload credential is authenticated as a workload and must
    never fall back to a human session. Unknown token ids take the native
    session path. Wrong secrets fail closed on their own path.
    """

    def __init__(
        self,
        *,
        native_subject_resolver: HttpSubjectResolver,
        workload_authenticator: WorkloadCredentialAuthenticator,
        workload_credential_reader: WorkloadCredentialReader,
    ) -> None:
        self._native = native_subject_resolver
        self._workload_authenticator = workload_authenticator
        self._workload_credential_reader = workload_credential_reader

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        raw_token = bearer_token(request)
        try:
            parsed = parse_workload_token(raw_token)
        except WorkloadCredentialInvalid:
            return await self._native.resolve_subject(request)
        snapshot = await self._workload_credential_reader.read_workload_credential(
            credential_id=parsed.credential_id
        )
        if snapshot is None:
            return await self._native.resolve_subject(request)
        subject = await self._workload_authenticator.authenticate(
            WorkloadCredentialEvidence(raw_token)
        )
        return AuthenticatedHttpSubject(
            subject=subject,
            authentication_method=_WORKLOAD_AUTHENTICATION_METHOD,
            credential_id=str(parsed.credential_id),
        )


__all__ = [
    "DispatchedBearerSubjectResolver",
    "WorkloadHttpSubjectResolver",
]
