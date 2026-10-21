from typing import Any, cast
from uuid import UUID

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.presentation import (
    TENANT_CONFIGURATION_OPERATION_IDS,
    TENANT_RUNTIME_EXTERNAL_DESTINATIONS,
    operator_coverage_gaps,
    stale_surface_operation_ids,
)
from request_engine.entrypoints.http.admin_console.routes_clinic_setup import (
    CLINIC_SETUP_OPERATION_IDS,
)
from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app


def _control_openapi() -> dict[str, Any]:
    inert_session_factory = cast(Any, object())
    app = create_platform_control_app(
        auth_session_factory=inert_session_factory,
        platform_read_session_factory=inert_session_factory,
        platform_write_session_factory=inert_session_factory,
        native_authority_id=UUID("00000000-0000-0000-0000-000000000001"),
        webauthn_decoy_key=b"admin-coverage-contract-key-32-bytes",
    )
    return app.openapi()


def test_every_operator_operation_has_an_explicit_admin_surface() -> None:
    catalog = load_catalog(_control_openapi())
    assert operator_coverage_gaps(catalog) == ()


def test_admin_surface_has_no_stale_operation_references() -> None:
    catalog = load_catalog(_control_openapi())
    assert stale_surface_operation_ids(catalog) == ()


def test_clinic_setup_projects_only_mounted_owner_operations() -> None:
    # The guided clinic setup is a projection: every owner operation it runs must
    # exist in the real runtime OpenAPI with its own capability; every mutation
    # must require an Idempotency-Key (the flow derives one per form intent); and
    # every operator operation it projects must already have an explicit admin
    # destination (the advanced configuration catalog or a declared workspace),
    # so the setup flow never becomes a second, undeclared surface.
    runtime = load_catalog(
        create_native_app(
            session_factory=cast(Any, object()),
            native_identity_authority_id=UUID("00000000-0000-0000-0000-000000000001"),
            appointment_option_signing_key=b"clinic-setup-coverage-signing-key-32",
        ).openapi()
    ).by_id()
    assert not CLINIC_SETUP_OPERATION_IDS - runtime.keys()
    declared = TENANT_CONFIGURATION_OPERATION_IDS | TENANT_RUNTIME_EXTERNAL_DESTINATIONS.keys()
    for operation_id in CLINIC_SETUP_OPERATION_IDS:
        operation = runtime[operation_id]
        assert operation.capability, operation_id
        if operation.is_mutating:
            assert operation.requires_idempotency_key, operation_id
        if operation.exposure == "operator":
            assert operation_id in declared, operation_id
