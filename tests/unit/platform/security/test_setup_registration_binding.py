"""Unit proof that setup WebAuthn completion is bound to the presented SetupSession.

This isolates the Python-layer check in ``NativeWebAuthnAuthService``: the store
double owns the challenge for SetupSession A, so completing with SetupSession B
must be rejected before any finalization. The PostgreSQL layer applies the same
check and is proven separately in ``tests/db/test_instance_claim.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyError,
    WebAuthnChallengeScope,
    WebAuthnCredentialRecord,
)
from request_engine.platform.security.webauthn import WebAuthnPolicy

pytestmark = [pytest.mark.unit, pytest.mark.adversarial, pytest.mark.security]

RP_ID = "localhost"
ORIGIN = "http://localhost:8000"


class _ChallengeOwnerStore:
    """Minimal store double whose only challenge is owned by one SetupSession."""

    def __init__(self, *, owner_setup_session_id: UUID) -> None:
        self._owner = owner_setup_session_id
        self.finalized_sessions: list[UUID] = []

    async def create_challenge(self, **_: object) -> bool:
        raise AssertionError("create_challenge must not be called")

    async def read_challenge(
        self, *, challenge_digest: bytes, purpose: str
    ) -> WebAuthnChallengeScope:
        assert purpose == "registration"
        return WebAuthnChallengeScope(
            native_identity_id=None,
            session_id=None,
            setup_session_id=self._owner,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def read_credential(self, *, credential_id: bytes) -> WebAuthnCredentialRecord | None:
        raise AssertionError("read_credential must not be called")

    async def read_credentials(
        self, *, native_identity_id: UUID
    ) -> tuple[WebAuthnCredentialRecord, ...]:
        raise AssertionError("read_credentials must not be called")

    async def finalize_registration(self, **_: object) -> bool:
        raise AssertionError("finalize_registration must not be called")

    async def finalize_authentication(self, **_: object) -> bool:
        raise AssertionError("finalize_authentication must not be called")

    async def finalize_step_up(self, **_: object) -> bool:
        raise AssertionError("finalize_step_up must not be called")

    async def finalize_setup_registration(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
        setup_session_id: UUID,
    ) -> bool:
        self.finalized_sessions.append(setup_session_id)
        return True


def _service(store: _ChallengeOwnerStore) -> NativeWebAuthnAuthService:
    return NativeWebAuthnAuthService(
        policy=WebAuthnPolicy(
            rp_id=RP_ID, rp_name="Request Engine", allowed_origins=frozenset({ORIGIN})
        ),
        store=store,
    )


def _credential() -> Mapping[str, Any]:
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    return authenticator.registration_credential(challenge=b"\x42" * 32, user_verified=True)


@pytest.mark.asyncio
async def test_setup_registration_rejects_non_owning_setup_session() -> None:
    owner = uuid4()
    store = _ChallengeOwnerStore(owner_setup_session_id=owner)
    service = _service(store)

    with pytest.raises(WebAuthnCeremonyError):
        await service.complete_setup_registration(
            setup_session_id=uuid4(), credential=_credential()
        )
    assert store.finalized_sessions == []


@pytest.mark.asyncio
async def test_setup_registration_accepts_owning_setup_session() -> None:
    owner = uuid4()
    store = _ChallengeOwnerStore(owner_setup_session_id=owner)
    service = _service(store)

    assert await service.complete_setup_registration(
        setup_session_id=owner, credential=_credential()
    )
    assert store.finalized_sessions == [owner]
