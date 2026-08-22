from __future__ import annotations

import pytest

from .operational_http_surface import (
    DISCOVERY_SCOPE,
    OPERATIONAL_HTTP_OPERATIONS,
    PROFILE_SCOPE,
    SUPPLY_SCOPE,
    TERMS_SCOPE,
)

_ALLOWED_SCOPES = frozenset({PROFILE_SCOPE, SUPPLY_SCOPE, TERMS_SCOPE, DISCOVERY_SCOPE})


@pytest.mark.e2e
@pytest.mark.contract
def test_operational_registry_classifies_authority_revision_and_durable_effect() -> None:
    for operation in OPERATIONAL_HTTP_OPERATIONS:
        assert operation.authority_scope in _ALLOWED_SCOPES, operation.name
        assert operation.idempotency_required, operation.name
        assert operation.tenant_isolation, operation.name
        assert operation.stale_semantics, operation.name
        assert operation.durable_effect, operation.name
        if operation.revision_owner is None:
            assert "expected" not in operation.stale_semantics, operation.name
        else:
            assert "expected" in operation.stale_semantics, operation.name


@pytest.mark.e2e
@pytest.mark.contract
def test_operational_registry_scope_families_are_explicit() -> None:
    by_name = {operation.name: operation for operation in OPERATIONAL_HTTP_OPERATIONS}
    assert by_name["organization.profile"].authority_scope == PROFILE_SCOPE
    assert by_name["locations.hours"].authority_scope == PROFILE_SCOPE
    assert by_name["resource_assignments.create"].authority_scope == SUPPLY_SCOPE
    assert by_name["resources.exception"].authority_scope == SUPPLY_SCOPE
    assert by_name["offering_version.booking_terms"].authority_scope == TERMS_SCOPE
    assert by_name["context_terms.supersede"].authority_scope == TERMS_SCOPE
    assert by_name["discovery.mapping"].authority_scope == DISCOVERY_SCOPE
    assert by_name["discovery.mapping_revoke"].authority_scope == DISCOVERY_SCOPE
    assert by_name["discovery.publish"].authority_scope == DISCOVERY_SCOPE
    assert by_name["discovery.revoke"].authority_scope == DISCOVERY_SCOPE
