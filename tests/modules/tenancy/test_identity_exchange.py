from uuid import uuid4

import pytest

from request_engine.modules.tenancy.api.identity_exchange_dependencies import (
    require_operator_document_witness,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeOperatorRequired,
)
from request_engine.modules.tenancy.domain.identity_exchange import (
    ScopedIdentityDocument,
    identity_document_fingerprint,
    normalize_portable_fields,
    normalize_witnessed_document,
    require_adoptable_fields,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

_KEY = b"identity-exchange-test-key-32-bytes-minimum"


def test_cedula_fingerprint_is_stable_keyed_and_not_the_document() -> None:
    document = normalize_witnessed_document("cedula", None, "402-1234567-8")
    first = identity_document_fingerprint(_KEY, document)
    assert document.authority == "DO:JCE"
    assert first == identity_document_fingerprint(
        _KEY, ScopedIdentityDocument("cedula", "DO:JCE", "40212345678")
    )
    assert document.value not in first
    assert len(first) == 64
    assert first != identity_document_fingerprint(
        b"different-identity-exchange-key-32bytes", document
    )


def test_passport_fingerprint_is_namespaced_by_issuing_country() -> None:
    dominican = normalize_witnessed_document("passport", "do", "sc1234567")
    american = normalize_witnessed_document("passport", "US", "sc1234567")
    assert dominican.value == american.value == "SC1234567"
    assert dominican.authority == "DO"
    assert identity_document_fingerprint(_KEY, dominican) != identity_document_fingerprint(
        _KEY, american
    )


def test_passport_requires_assigned_iso_issuing_authority() -> None:
    with pytest.raises(ValueError, match="issuing authority is required"):
        normalize_witnessed_document("passport", None, "SC1234567")
    for invalid in ("DOM", "RD", "ZZ", "XX"):
        with pytest.raises(ValueError, match="assigned ISO-3166"):
            normalize_witnessed_document("passport", invalid, "SC1234567")


def test_identity_exchange_has_no_insecure_key_fallback() -> None:
    document = ScopedIdentityDocument("passport", "DO", "SC1234567")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        identity_document_fingerprint(None, document)
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        identity_document_fingerprint(b"too-short", document)


def test_portable_consent_is_allowlisted_and_adoption_requires_name() -> None:
    assert normalize_portable_fields(("display_name", "phone", "phone")) == (
        "display_name",
        "phone",
    )
    with pytest.raises(ValueError, match="unsupported portable fields"):
        normalize_portable_fields(("display_name", "appointments"))
    with pytest.raises(ValueError, match="display_name consent"):
        require_adoptable_fields(("phone",))


def test_raw_integration_cannot_assert_operator_document_witness() -> None:
    integration = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"identity_exchange.match"}),
        principal_kind=PrincipalKind.INTEGRATION,
    )
    with pytest.raises(IdentityExchangeOperatorRequired):
        require_operator_document_witness(integration)


def test_effective_human_operator_can_assert_document_witness() -> None:
    human = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"identity_exchange.match"}),
        principal_kind=PrincipalKind.HUMAN,
    )
    require_operator_document_witness(human)
