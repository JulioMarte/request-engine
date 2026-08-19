import os
from typing import cast

import pytest
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


def _assert_runtime_login_name(current_user: str) -> None:
    expected = os.environ.get("REQUEST_ENGINE_APP_ROLE_NAME")
    if expected is not None:
        assert current_user == expected
    else:
        assert current_user.startswith("request_engine_app_test_")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_first_vertical_uses_real_least_privileged_app_login(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        current_user,
                        session_user,
                        r.rolsuper,
                        r.rolbypassrls,
                        r.rolcreaterole,
                        r.rolcreatedb,
                        pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                        pg_has_role(current_user, 'request_engine_admin', 'MEMBER'),
                        pg_has_role(current_user, 'request_engine_worker', 'MEMBER')
                    FROM pg_roles r
                    WHERE r.rolname = current_user
                    """
                )
            )
        ).one()

    current_user = cast(str, row[0])
    session_user = cast(str, row[1])
    assert current_user == session_user
    _assert_runtime_login_name(current_user)
    assert row[2:6] == (False, False, False, False)
    assert row[6] is True
    assert row[7] is False
    assert row[8] is False
