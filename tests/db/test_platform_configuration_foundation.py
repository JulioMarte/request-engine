"""Private platform configuration/secret-binding foundation proofs (ADR 0015)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


def _binding(admin_conn: PgConnection, *, purpose: str = "email.smtp.password") -> UUID:
    binding_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.platform_secret_bindings (
            id, purpose, backend, secret_id, backend_version
        ) VALUES (%s, %s, 'openbao', %s, 1)
        """,
        (binding_id, purpose, uuid4()),
    )
    return binding_id


def _revision(
    admin_conn: PgConnection,
    *,
    kind: str = "email.delivery",
    revision: int = 1,
    binding_id: UUID | None = None,
) -> UUID:
    revision_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.platform_configuration_revisions (
            id, configuration_kind, provider_kind, revision,
            configuration, secret_binding_id
        ) VALUES (%s, %s, 'smtp', %s, %s::jsonb, %s)
        """,
        (
            revision_id,
            kind,
            revision,
            '{"host":"mail.internal","port":587,"security":"starttls"}',
            binding_id,
        ),
    )
    return revision_id


def test_platform_configuration_tables_are_private_to_app(
    admin_conn: PgConnection,
) -> None:
    for table in (
        "platform_secret_bindings",
        "platform_configuration_revisions",
        "platform_configuration_facts",
    ):
        privileges = admin_conn.execute(
            """
            SELECT
              has_table_privilege('request_engine_app', %s, 'SELECT'),
              has_table_privilege('request_engine_app', %s, 'INSERT'),
              has_table_privilege('request_engine_app', %s, 'UPDATE'),
              has_table_privilege('request_engine_app', %s, 'DELETE')
            """,
            (f"request_engine.{table}",) * 4,
        ).fetchone()
        assert privileges == (False, False, False, False)


def test_only_one_active_revision_per_kind(admin_conn: PgConnection) -> None:
    first = _revision(admin_conn, revision=1)
    second = _revision(admin_conn, revision=2)

    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'validated', validated_at = clock_timestamp()
         WHERE id = %s
        """,
        (first,),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'active', activated_at = clock_timestamp()
         WHERE id = %s
        """,
        (first,),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'validated', validated_at = clock_timestamp()
         WHERE id = %s
        """,
        (second,),
    )

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            """
            UPDATE request_engine.platform_configuration_revisions
               SET state = 'active', activated_at = clock_timestamp()
             WHERE id = %s
            """,
            (second,),
        )


def test_payload_and_secret_binding_are_immutable_after_stage(
    admin_conn: PgConnection,
) -> None:
    binding = _binding(admin_conn)
    revision_id = _revision(admin_conn, binding_id=binding)

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            """
            UPDATE request_engine.platform_configuration_revisions
               SET configuration = '{"host":"attacker"}'::jsonb
             WHERE id = %s
            """,
            (revision_id,),
        )

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            """
            UPDATE request_engine.platform_configuration_revisions
               SET secret_binding_id = NULL
             WHERE id = %s
            """,
            (revision_id,),
        )


def test_lifecycle_is_monotonic_and_superseded_is_terminal(
    admin_conn: PgConnection,
) -> None:
    revision_id = _revision(admin_conn)
    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'validated', validated_at = clock_timestamp()
         WHERE id = %s
        """,
        (revision_id,),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'active', activated_at = clock_timestamp()
         WHERE id = %s
        """,
        (revision_id,),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.platform_configuration_revisions
           SET state = 'superseded'
         WHERE id = %s
        """,
        (revision_id,),
    )

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            """
            UPDATE request_engine.platform_configuration_revisions
               SET state = 'active'
             WHERE id = %s
            """,
            (revision_id,),
        )


def test_secret_binding_rotation_is_version_monotonic_and_identity_is_immutable(
    admin_conn: PgConnection,
) -> None:
    binding_id = _binding(admin_conn)
    original_secret_id = admin_conn.execute(
        "SELECT secret_id FROM request_engine.platform_secret_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert original_secret_id is not None

    admin_conn.execute(
        """
        UPDATE request_engine.platform_secret_bindings
           SET backend_version = 2,
               revision = revision + 1,
               rotated_at = clock_timestamp()
         WHERE id = %s
        """,
        (binding_id,),
    )

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            """
            UPDATE request_engine.platform_secret_bindings
               SET backend_version = 1,
                   revision = revision + 1,
                   rotated_at = clock_timestamp()
             WHERE id = %s
            """,
            (binding_id,),
        )

    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            "UPDATE request_engine.platform_secret_bindings SET secret_id = %s WHERE id = %s",
            (uuid4(), binding_id),
        )


def test_configuration_facts_are_append_only(admin_conn: PgConnection) -> None:
    fact_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.platform_configuration_facts (
            id, event_kind, configuration_kind, revision
        ) VALUES (%s, 'staged', 'email.delivery', 1)
        """,
        (fact_id,),
    )
    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            "UPDATE request_engine.platform_configuration_facts "
            "SET event_kind = 'validated' WHERE id = %s",
            (fact_id,),
        )
