from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection
from psycopg.errors import InsufficientPrivilege

PgConnection = Connection[Any]

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def test_http_runtime_reads_only_active_appointment_signing_reference(
    admin_conn: PgConnection,
    app_role_conn_factory: Callable[[], PgConnection],
) -> None:
    binding_id = uuid4()
    secret_id = uuid4()
    config_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.platform_secret_bindings (
            id, purpose, backend, secret_id, backend_version, status, revision
        ) VALUES (%s, 'security.appointment_option_signing', 'openbao', %s, 3, 'active', 2)
        """,
        (binding_id, secret_id),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.platform_configuration_revisions (
            id, configuration_kind, provider_kind, revision, configuration,
            secret_binding_id, state, created_by_principal_id,
            validated_at, activated_at
        ) VALUES (
            %s,
            'security.appointment_option_signing',
            'hmac-sha256-keyring',
            7,
            '{}'::jsonb,
            %s,
            'active',
            NULL,
            clock_timestamp(),
            clock_timestamp()
        )
        """,
        (config_id, binding_id),
    )
    try:
        with app_role_conn_factory() as app:
            row = app.execute(
                "SELECT * FROM "
                "request_platform.read_active_appointment_option_signing_keyring()"
            ).fetchone()
            assert row == (7, 2, secret_id, 3)

            with pytest.raises(InsufficientPrivilege):
                app.execute(
                    "SELECT * FROM "
                    "request_platform.read_active_platform_runtime_configuration(%s)",
                    ("email.delivery",),
                )
    finally:
        admin_conn.execute(
            "DELETE FROM request_engine.platform_configuration_revisions WHERE id = %s",
            (config_id,),
        )
        admin_conn.execute(
            "DELETE FROM request_engine.platform_secret_bindings WHERE id = %s",
            (binding_id,),
        )


def test_http_runtime_signing_projection_fails_closed_without_active_binding(
    app_role_conn: PgConnection,
) -> None:
    row = app_role_conn.execute(
        "SELECT * FROM request_platform.read_active_appointment_option_signing_keyring()"
    ).fetchone()
    assert row is None
