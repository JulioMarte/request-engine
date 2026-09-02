from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class F7eSelectionFixture:
    organization_id: UUID
    principal_id: UUID
    queue_id: UUID
    entry_ids: tuple[UUID, UUID, UUID]


def _uuid_row(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_f7e_selection_fixture(conn: PgConnection) -> F7eSelectionFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.organizations (organization_key,display_name) "
        "VALUES (%s,'F7e Clinic') RETURNING id",
        (f"f7e-{suffix}",),
    )
    principal_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) "
        "VALUES (%s,'human',%s) RETURNING id",
        (organization_id, f"operator-{suffix}"),
    )
    queue_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.service_queues "
        "(organization_id,queue_key,display_name) VALUES (%s,%s,'Front Desk') RETURNING id",
        (organization_id, f"front-{suffix}"),
    )
    entry_ids: list[UUID] = []
    for index, minute in enumerate((0, 5, 10), start=1):
        party_id = _uuid_row(
            conn,
            "INSERT INTO request_engine.parties (organization_id,party_kind,display_name) "
            "VALUES (%s,'person',%s) RETURNING id",
            (organization_id, f"Patient {index}"),
        )
        entry_ids.append(
            _uuid_row(
                conn,
                "INSERT INTO request_engine.queue_entries "
                "(organization_id,service_queue_id,subject_party_id,status,arrived_at,admitted_at) "
                "VALUES (%s,%s,%s,'waiting',"
                "make_timestamptz(2035,1,1,9,%s,0,'UTC'),"
                "make_timestamptz(2035,1,1,9,%s,0,'UTC')) RETURNING id",
                (organization_id, queue_id, party_id, minute, minute),
            )
        )
    return F7eSelectionFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        entry_ids=cast(tuple[UUID, UUID, UUID], tuple(entry_ids)),
    )
