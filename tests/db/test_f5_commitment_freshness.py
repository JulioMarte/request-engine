# Direct PostgreSQL proof for the F5 contract (docs/v3/32, section 5): a
# Reservation/CapacityClaim commitment that enters, moves or leaves the assessed
# recovery scope must durably advance the recovery source revision once per
# material row change and enqueue exactly one F5 reassessment per new revision,
# while commitments outside the assessed scope change nothing.

from uuid import UUID

import pytest
from f2_discovery_fixture import create_discovery_fixture, uuid_row
from f3_live_ops_seed import PgConnection

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.invariant,
    pytest.mark.contract,
]


def _state(conn: PgConnection, org: UUID, queue: UUID) -> tuple[int, int, int]:
    # (revision, reassessment actions deduped for the current revision, total)
    row = conn.execute(
        "SELECT r.revision, "
        "(SELECT count(*) FROM request_engine.scheduled_actions a "
        "WHERE a.organization_id=r.organization_id "
        "AND a.dedupe_key=format('f5-reassessment:%%s:%%s',r.service_queue_id,r.revision)), "
        "(SELECT count(*) FROM request_engine.scheduled_actions a "
        "WHERE a.organization_id=r.organization_id AND a.dedupe_key LIKE 'f5-reassessment:%%') "
        "FROM request_engine.recovery_source_revisions r "
        "WHERE r.organization_id=%s AND r.service_queue_id=%s",
        (org, queue),
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


def test_booking_commitments_advance_recovery_source_revision(admin_conn: PgConnection) -> None:
    base = create_discovery_fixture(admin_conn)
    org = base.organization_id
    queue_id = uuid_row(
        admin_conn,
        "INSERT INTO request_engine.service_queues (organization_id,location_id,offering_id,"
        "queue_key,display_name) VALUES (%s,%s,%s,'commitment-freshness','Freshness Queue') "
        "RETURNING id",
        (org, base.location_id, base.offering_id),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_projection_policies "
        "(organization_id,service_queue_id,resource_id,location_id) VALUES (%s,%s,%s,%s)",
        (org, queue_id, base.resource_id, base.location_id),
    )
    # Resource at the same location but pinned by no projection policy: off-scope.
    off_resource_id = uuid_row(
        admin_conn,
        "INSERT INTO request_engine.resources (organization_id,resource_key,display_name,"
        "capacity_model,capacity_units) VALUES (%s,'offscope','Off Scope','exclusive',1) "
        "RETURNING id",
        (org,),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.resource_capability_assignments "
        "(organization_id,resource_id,capability_id) "
        "SELECT %s,%s,capability_id FROM request_engine.offering_resource_requirements "
        "WHERE organization_id=%s AND id=%s",
        (org, off_resource_id, org, base.requirement_id),
    )
    # Open recovery context pinned to a known, non-default revision.
    admin_conn.execute(
        "INSERT INTO request_engine.recovery_source_revisions "
        "(organization_id,service_queue_id,revision) VALUES (%s,%s,7) "
        "ON CONFLICT (organization_id,service_queue_id) DO UPDATE SET revision=7",
        (org, queue_id),
    )
    assert _state(admin_conn, org, queue_id) == (7, 0, 1)

    # 1. A commitment entering the assessed scope advances the revision once.
    with admin_conn.transaction():
        reservation_id = uuid_row(
            admin_conn,
            "INSERT INTO request_engine.reservations (organization_id,offering_version_id,"
            "subject_party_id,location_id,during) VALUES (%s,%s,%s,%s,"
            "tstzrange('2035-01-05T10:00Z','2035-01-05T10:30Z','[)')) RETURNING id",
            (org, base.offering_version_id, base.party_id, base.location_id),
        )
        claim_id = uuid_row(
            admin_conn,
            "INSERT INTO request_engine.capacity_claims (organization_id,resource_id,"
            "requirement_id,reservation_id,during,quantity) VALUES (%s,%s,%s,%s,"
            "tstzrange('2035-01-05T10:00Z','2035-01-05T10:30Z','[)'),1) RETURNING id",
            (org, base.resource_id, base.requirement_id, reservation_id),
        )
    assert _state(admin_conn, org, queue_id) == (8, 1, 2)

    # 2. Moving the commitment interval advances it again, once per material row.
    with admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.reservations SET during="
            "tstzrange('2035-01-05T12:00Z','2035-01-05T12:30Z','[)'),revision=revision+1,"
            "updated_at=clock_timestamp() WHERE organization_id=%s AND id=%s",
            (org, reservation_id),
        )
        admin_conn.execute(
            "UPDATE request_engine.capacity_claims SET during="
            "tstzrange('2035-01-05T12:00Z','2035-01-05T12:30Z','[)'),updated_at=clock_timestamp() "
            "WHERE organization_id=%s AND id=%s",
            (org, claim_id),
        )
    assert _state(admin_conn, org, queue_id) == (10, 1, 4)

    # 3. Leaving the scope (release then cancel, production order) advances once.
    with admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.capacity_claims SET status='released',"
            "released_at=clock_timestamp(),updated_at=clock_timestamp() "
            "WHERE organization_id=%s AND id=%s",
            (org, claim_id),
        )
        admin_conn.execute(
            "UPDATE request_engine.reservations SET status='cancelled',"
            "cancelled_at=clock_timestamp(),revision=revision+1,updated_at=clock_timestamp() "
            "WHERE organization_id=%s AND id=%s",
            (org, reservation_id),
        )
    assert _state(admin_conn, org, queue_id) == (11, 1, 5)

    # 4. A hold-only commitment outside the assessed scope changes nothing.
    with admin_conn.transaction():
        hold_id = uuid_row(
            admin_conn,
            "INSERT INTO request_engine.capacity_holds (organization_id,offering_version_id,"
            "subject_party_id,location_id,during,expires_at) VALUES (%s,%s,%s,%s,"
            "tstzrange('2035-01-05T10:00Z','2035-01-05T10:30Z','[)'),"
            "clock_timestamp()+interval '1 day') RETURNING id",
            (org, base.offering_version_id, base.party_id, base.location_id),
        )
        admin_conn.execute(
            "INSERT INTO request_engine.capacity_claims (organization_id,resource_id,"
            "requirement_id,hold_id,during,quantity) VALUES (%s,%s,%s,%s,"
            "tstzrange('2035-01-05T10:00Z','2035-01-05T10:30Z','[)'),1)",
            (org, off_resource_id, base.requirement_id, hold_id),
        )
    assert _state(admin_conn, org, queue_id) == (11, 1, 5)
