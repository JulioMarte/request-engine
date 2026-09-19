import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.oidc_auth import OidcAuthorityConfig


class PostgresOidcAuthorityReader:
    """Read active OIDC authorities through the narrow request_auth boundary.

    Only well-formed active authorities are returned: a row whose
    ``configuration_ref`` does not parse into ``{"jwks_uri": ..., "audience":
    ...}`` is invisible to issuer routing, so a broken authority row can never
    become a routing target. The reader never follows provider links and holds
    no locks.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_active_authorities(self) -> tuple[OidcAuthorityConfig, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id,
                                   issuer_or_environment,
                                   configuration_ref
                              FROM request_auth.read_oidc_authorities()
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            config
            for config in (parse_oidc_authority(dict(row)) for row in rows)
            if config is not None
        )


def parse_oidc_authority(row: dict[str, Any]) -> OidcAuthorityConfig | None:
    """Parse a persisted configuration; malformed entries have no routing authority."""
    configuration_ref = row["configuration_ref"]
    if not isinstance(configuration_ref, str):
        return None
    try:
        configuration: Any = json.loads(configuration_ref)
        if not isinstance(configuration, dict):
            return None
        fields = cast(dict[str, Any], configuration)
        jwks_uri = fields["jwks_uri"]
        audience = fields["audience"]
    except (json.JSONDecodeError, TypeError, KeyError, RecursionError):
        return None
    if not isinstance(jwks_uri, str) or not isinstance(audience, str):
        return None
    try:
        authority_id = UUID(str(row["id"]))
        return OidcAuthorityConfig(
            authority_id=authority_id,
            issuer=row["issuer_or_environment"],
            jwks_uri=jwks_uri,
            audience=audience,
        )
    except (ValueError, TypeError, KeyError):
        return None
