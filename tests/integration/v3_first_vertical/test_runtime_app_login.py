from typing import cast

import pytest
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


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
    assert current_user.startswith("request_engine_app_test_")
    assert row[2:6] == (False, False, False, False)
    assert row[6] is True
    assert row[7] is False
    assert row[8] is False
