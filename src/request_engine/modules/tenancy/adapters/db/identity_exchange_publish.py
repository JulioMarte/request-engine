"""PostgreSQL publication adapter for S0d portable identity profiles."""

from sqlalchemy.exc import IntegrityError

from request_engine.modules.tenancy.adapters.db import identity_exchange_conflicts
from request_engine.modules.tenancy.adapters.db.identity_exchange_publish_tx import (
    write_portable_profile,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    PublishPortableProfileCommand,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeIdentityConflict,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresPortableProfilePublisher:
    def __init__(self, session_factory: SessionFactory, fingerprint_key: bytes | None) -> None:
        self._session_factory = session_factory
        self._fingerprint_key = fingerprint_key

    async def publish_portable_profile(self, command: PublishPortableProfileCommand) -> None:
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                await write_portable_profile(
                    session,
                    command,
                    fingerprint_key=self._fingerprint_key,
                )
        except IntegrityError as exc:
            if identity_exchange_conflicts.is_portable_identity_join_violation(exc):
                raise IdentityExchangeIdentityConflict(
                    "document would join two portable identities"
                ) from None
            raise
