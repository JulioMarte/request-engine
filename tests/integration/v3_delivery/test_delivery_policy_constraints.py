import json
from typing import Any

import pytest
from psycopg import Connection
from psycopg.errors import CheckViolation

from ._fixture import DeliveryFixture, make_delivery_fixture

PgConnection = Connection[Any]


def _insert_delivery_policy(
    conn: PgConnection,
    fixture: DeliveryFixture,
    policy: object,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable,
            booking_policy, delivery_policy
        ) VALUES (%s, %s, 2, 30, true, %s::jsonb, %s::jsonb)
        """,
        (
            fixture.organization_id,
            fixture.offering_id,
            json.dumps({"slot_step_minutes": 15}),
            json.dumps(policy),
        ),
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize(
    "policy",
    [
        {"access": {}},
        {"access": ["not-an-object"]},
        {"access": [{"kind": "video_link", "provider": "meeting"}]},
        {
            "access": [
                {"key": "video", "kind": "video_link", "provider": "meeting"},
                {"key": "video", "kind": "phone", "provider": "meeting"},
            ]
        },
        {"access": [{"key": "video", "kind": "unsupported", "provider": "meeting"}]},
        {
            "access": [
                {
                    "key": "video",
                    "kind": "video_link",
                    "provider": "meeting",
                    "provisioning": "eventually",
                }
            ]
        },
        {
            "access": [
                {
                    "key": "address",
                    "kind": "physical_location",
                    "public_data": [],
                }
            ]
        },
        {"access": [{"key": "address", "kind": "physical_location"}]},
    ],
)
def test_postgres_rejects_malformed_delivery_policy(
    admin_conn: PgConnection,
    policy: object,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {
                "key": "address",
                "kind": "physical_location",
                "public_data": {"line1": "Main 1"},
            }
        ],
    )

    with pytest.raises(CheckViolation), admin_conn.transaction():
        _insert_delivery_policy(admin_conn, fixture, policy)


@pytest.mark.integration
@pytest.mark.postgres
def test_postgres_accepts_provider_backed_immediate_policy(
    admin_conn: PgConnection,
) -> None:
    fixture = make_delivery_fixture(
        admin_conn,
        access_policies=[
            {
                "key": "address",
                "kind": "physical_location",
                "public_data": {"line1": "Main 1"},
            }
        ],
    )

    with admin_conn.transaction():
        _insert_delivery_policy(
            admin_conn,
            fixture,
            {
                "access": [
                    {
                        "key": "video",
                        "kind": "video_link",
                        "provider": "meeting",
                    }
                ]
            },
        )
