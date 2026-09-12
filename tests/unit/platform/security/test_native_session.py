from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from request_engine.platform.security.native_auth import CredentialInvalid, issue_opaque_token
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityDisabled,
    NativeIdentityStatus,
    NativeSessionAuthenticator,
    NativeSessionEvidence,
    NativeSessionSnapshot,
    NativeSessionStatus,
    SessionExpired,
    SessionRevoked,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

NOW = datetime(2026, 9, 8, tzinfo=UTC)


class FakeSessionReader:
    def __init__(self, session: NativeSessionSnapshot | None) -> None:
        self.session = session

    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None:
        if self.session is None or self.session.session_id != session_id:
            return None
        return self.session


def _snapshot(
    *,
    token_digest: bytes,
    session_id: UUID,
    session_epoch: int = 3,
    current_session_epoch: int = 3,
    session_status: NativeSessionStatus = NativeSessionStatus.ACTIVE,
    identity_status: NativeIdentityStatus = NativeIdentityStatus.ACTIVE,
    credential_status: NativeCredentialStatus = NativeCredentialStatus.ACTIVE,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> NativeSessionSnapshot:
    return NativeSessionSnapshot(
        session_id=session_id,
        native_identity_id=uuid4(),
        identity_authority_id=uuid4(),
        credential_id=uuid4(),
        token_digest=token_digest,
        session_epoch=session_epoch,
        current_session_epoch=current_session_epoch,
        session_status=session_status,
        identity_status=identity_status,
        credential_status=credential_status,
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_valid_session_authenticates_only_identity_not_authority() -> None:
    material = issue_opaque_token()
    session = _snapshot(token_digest=material.digest, session_id=material.token_id)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    subject = await authenticator.authenticate(NativeSessionEvidence(material.raw_token))

    assert subject.subject_id == str(session.native_identity_id)
    assert subject.authority_id == str(session.identity_authority_id)
    assert "capabilities" not in subject.metadata


@pytest.mark.asyncio
async def test_wrong_secret_fails_as_invalid_credential() -> None:
    material = issue_opaque_token()
    other = issue_opaque_token(token_id=material.token_id)
    session = _snapshot(token_digest=material.digest, session_id=material.token_id)
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(CredentialInvalid):
        await authenticator.authenticate(NativeSessionEvidence(other.raw_token))


@pytest.mark.asyncio
async def test_session_epoch_change_invalidates_existing_session_immediately() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        session_epoch=3,
        current_session_epoch=4,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(SessionRevoked):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_disabled_identity_invalidates_existing_session() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        identity_status=NativeIdentityStatus.DISABLED,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(NativeIdentityDisabled):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))


@pytest.mark.asyncio
async def test_expired_session_fails_closed() -> None:
    material = issue_opaque_token()
    session = _snapshot(
        token_digest=material.digest,
        session_id=material.token_id,
        expires_at=NOW,
    )
    authenticator = NativeSessionAuthenticator(
        session_reader=FakeSessionReader(session),
        clock=lambda: NOW,
    )

    with pytest.raises(SessionExpired):
        await authenticator.authenticate(NativeSessionEvidence(material.raw_token))
