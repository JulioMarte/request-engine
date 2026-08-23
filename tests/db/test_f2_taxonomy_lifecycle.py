from typing import Any
from uuid import UUID

import pytest
from psycopg import Connection

PgConnection = Connection[Any]


@pytest.mark.postgres
@pytest.mark.security
def test_taxonomy_admin_lifecycle_is_narrow_audited_and_append_only(
    admin_conn: PgConnection,
) -> None:
    created = admin_conn.execute(
        "SELECT request_admin.create_service_classification(%s,%s,%s,%s)",
        ("f2_taxonomy_proof", "F2 Taxonomy Proof", "platform-admin:test", "create proof"),
    ).fetchone()
    assert created is not None
    classification_id = created[0]
    assert isinstance(classification_id, UUID)
    assert admin_conn.execute(
        "SELECT action, authority_ref, reason FROM "
        "request_engine.service_classification_authority_events "
        "WHERE service_classification_id=%s ORDER BY created_at",
        (classification_id,),
    ).fetchall() == [("created", "platform-admin:test", "create proof")]

    revision = admin_conn.execute(
        "SELECT request_admin.retire_service_classification(%s,1,%s,%s)",
        (classification_id, "platform-admin:test", "retire proof"),
    ).fetchone()
    assert revision == (2,)
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.service_classifications WHERE id=%s",
        (classification_id,),
    ).fetchone() == ("retired", 2)
    assert admin_conn.execute(
        "SELECT action FROM request_engine.service_classification_authority_events "
        "WHERE service_classification_id=%s ORDER BY created_at",
        (classification_id,),
    ).fetchall() == [("created",), ("retired",)]

    assert admin_conn.execute(
        "SELECT has_function_privilege('request_engine_app', "
        "'request_admin.create_service_classification(text,text,text,text)', 'EXECUTE')"
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT has_table_privilege('request_engine_app', "
        "'request_engine.service_classification_authority_events', 'SELECT')"
    ).fetchone() == (False,)
