from typing import Any, cast
from uuid import UUID

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.presentation import (
    operator_coverage_gaps,
    stale_surface_operation_ids,
)
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
