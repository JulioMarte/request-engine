import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.workload_auth import (
    WorkloadAuthorityStatus,
    WorkloadCredentialAuthenticator,
    WorkloadCredentialEvidence,
    WorkloadCredentialInvalid,
    WorkloadCredentialSnapshot,
    WorkloadCredentialStatus,
    WorkloadIdentityStatus,
    WorkloadKind,
)


class StaticWorkloadReader:
    def __init__(self, snapshot: WorkloadCredentialSnapshot | None) -> None:
        self.snapshot = snapshot
        self.requested_id: UUID | None = None

    async def read_workload_credential(
        self, *, credential_id: UUID
    ) -> WorkloadCredentialSnapshot | None:
        self.requested_id = credential_id
        return self.snapshot


def _snapshot(*, secret: str, identity_status: WorkloadIdentityStatus) -> WorkloadCredentialSnapshot:
    return WorkloadCredentialSnapshot(
        credential_id=uuid4(),
        workload_identity_id=uuid4(),
        identity_authority_id=uuid4(),
        workload_kind=WorkloadKind.AGENT,
        token_digest=hashlib.sha256(secret.encode("utf-8")).digest(),
        credential_status=WorkloadCredentialStatus.ACTIVE,
        identity_status=identity_status,
        authority_status=WorkloadAuthorityStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_workload_credential_produces_identity_without_authority() -> None:
    secret = "workload-test-secret"
    snapshot = _snapshot(secret=secret, identity_status=WorkloadIdentityStatus.ACTIVE)
    reader = StaticWorkloadReader(snapshot)
    authenticator = WorkloadCredentialAuthenticator(reader)

    subject = await authenticator.authenticate(
        WorkloadCredentialEvidence(f"{snapshot.credential_id}.{secret}")
    )

    assert subject.authority_id == str(snapshot.identity_authority_id)
    assert subject.subject_id == str(snapshot.workload_identity_id)
    assert subject.subject_class is AuthenticatedSubjectClass.WORKLOAD
    assert subject.metadata["workload_kind"] == "agent"
    assert reader.requested_id == snapshot.credential_id


@pytest.mark.asyncio
async def test_disabled_workload_identity_invalidates_existing_bearer() -> None:
    secret = "workload-test-secret"
    snapshot = _snapshot(secret=secret, identity_status=WorkloadIdentityStatus.DISABLED)
    authenticator = WorkloadCredentialAuthenticator(StaticWorkloadReader(snapshot))

    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(
            WorkloadCredentialEvidence(f"{snapshot.credential_id}.{secret}")
        )


@pytest.mark.asyncio
async def test_wrong_workload_secret_fails_closed() -> None:
    snapshot = _snapshot(
        secret="correct-workload-secret",
        identity_status=WorkloadIdentityStatus.ACTIVE,
    )
    authenticator = WorkloadCredentialAuthenticator(StaticWorkloadReader(snapshot))

    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(
            WorkloadCredentialEvidence(f"{snapshot.credential_id}.wrong-workload-secret")
        )
