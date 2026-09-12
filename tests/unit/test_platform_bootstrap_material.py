from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.platform.security.native_auth import verify_password
from request_engine.platform.security.platform_bootstrap import (
    issue_platform_bootstrap_material,
    parse_platform_bootstrap_token,
    prepare_platform_root,
)


def test_bootstrap_material_round_trips_only_digest_evidence() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    material = issue_platform_bootstrap_material(ttl=timedelta(minutes=12), now=now)

    intent_id, digest = parse_platform_bootstrap_token(material.raw_token)

    assert intent_id == material.intent_id
    assert digest == material.token_digest
    assert material.token_fingerprint == material.token_digest.hex()[:16]
    assert material.expires_at == now + timedelta(minutes=12)
    assert material.raw_token.encode() not in material.token_digest


def test_bootstrap_material_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="TTL must be positive"):
        issue_platform_bootstrap_material(ttl=timedelta(0))


def test_root_material_normalizes_login_and_derives_password_verifier() -> None:
    root = prepare_platform_root(
        login_handle="  Initial.Admin@Example.COM  ",
        password="correct horse battery staple",
    )

    identities = {
        root.native_identity_id,
        root.credential_id,
        root.principal_id,
        root.binding_id,
    }
    assert root.login_handle == "initial.admin@example.com"
    assert verify_password("correct horse battery staple", root.password_verifier)
    assert "correct horse battery staple" not in root.password_verifier
    assert len(identities) == 4
    assert all(isinstance(value, UUID) for value in identities)
