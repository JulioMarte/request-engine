from uuid import uuid4

import pytest

from request_engine.modules.tenancy.api.identity_exchange_dependencies import (
    require_operator_document_witness,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeOperatorRequired,
)
from request_engine.modules.tenancy.domain.identity_exchange import (
    cedula_fingerprint,
    normalize_portable_fields,
    normalize_witnessed_cedula,
    require_adoptable_fields,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

_KEY = b"identity-exchange-test-key-32-bytes-minimum"


def test_cedula_fingerprint_is_stable_keyed_and_not_the_document() -> None:
    cedula = normalize_witnessed_cedula("402-1234567-8")
    first = cedula_fingerprint(_KEY, cedula)
    assert first == cedula_fingerprint(_KEY, "40212345678")
    assert first != cedula
    assert len(first) == 64
    assert first != cedula_fingerprint(b"different-identity-exchange-key-32bytes", cedula)


def test_identity_exchange_has_no_insecure_key_fallback() -> None:
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        cedula_fingerprint(None, "40212345678")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        cedula_fingerprint(b"too-short", "40212345678")


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
