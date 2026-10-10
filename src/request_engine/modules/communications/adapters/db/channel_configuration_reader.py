from typing import cast

from sqlalchemy import text

from request_engine.modules.communications.application.queries.channel_configuration import (
    ChannelConfiguration,
    ChannelConfigurationQuery,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.db.tenant_principal_authority_reader import (
    require_current_tenant_capability,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    require_principal_serialized_operational_authority,
)


class PostgresChannelConfigurationReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_configuration(self, query: ChannelConfigurationQuery) -> ChannelConfiguration:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            await require_current_tenant_capability(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                capability="communications.read_configuration",
            )
            await require_principal_serialized_operational_authority(
                session,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                authority_party_id=query.authority_party_id,
                scope_key=MANAGE_OPERATIONAL_PROFILE_SCOPE,
            )
            row = (
                (
                    await session.execute(
                        text("""
                        SELECT enabled, channel_policy, revision
                        FROM request_engine.organization_channel_policies
                        WHERE organization_id = :organization_id AND purpose = :purpose
                    """),
                        {"organization_id": query.organization_id, "purpose": query.purpose},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return ChannelConfiguration(query.purpose, False, 0, None, None)
            return ChannelConfiguration(
                query.purpose,
                True,
                int(row["revision"]),
                bool(row["enabled"]),
                cast(dict[str, object], row["channel_policy"]),
            )
