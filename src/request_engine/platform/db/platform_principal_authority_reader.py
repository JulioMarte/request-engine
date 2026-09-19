from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.principal_authority import (
    PrincipalAuthorityMaterializationError,
    PrincipalAuthoritySnapshot,
)


def materialize_platform_authority(
    *, principal_id: UUID, rows: Sequence[Mapping[str, Any]]
) -> PrincipalAuthoritySnapshot | None:
    """Interpret the narrow platform DB projection and fail closed on registry drift."""

    if not rows:
        return None
    principal = rows[0]
    if not principal["active"]:
        return None

    capabilities: set[str] = set()
    delegable: set[str] = set()
    for row in rows:
        key = row["capability_key"]
        if key is None:
            continue
        definition = capability_definition(str(key))
        if definition is None:
            raise PrincipalAuthorityMaterializationError(f"unknown persisted capability: {key}")
        if definition.authority_plane is not AuthorityPlane.PLATFORM:
            raise PrincipalAuthorityMaterializationError(
                f"non-platform capability returned by platform authority boundary: {key}"
            )
        capabilities.add(str(key))
        if row["delegable"]:
            delegable.add(str(key))

    return PrincipalAuthoritySnapshot(
        principal_id=principal_id,
        principal_kind=str(principal["principal_kind"]),
        authority_revision=int(principal["authority_revision"]),
        capabilities=frozenset(capabilities),
        delegable_capabilities=frozenset(delegable),
    )


class PostgresPlatformPrincipalAuthorityReader:
    """Read platform authority only through the audited SECURITY DEFINER boundary."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_platform_principal_authority(
        self, *, principal_id: UUID
    ) -> PrincipalAuthoritySnapshot | None:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT principal_kind,
                                   active,
                                   authority_revision,
                                   capability_key,
                                   delegable
                              FROM request_platform.read_principal_authority(:principal_id)
                            """
                        ),
                        {"principal_id": principal_id},
                    )
                )
                .mappings()
                .all()
            )

        normalized_rows: list[dict[str, Any]] = [
            {
                "principal_kind": row["principal_kind"],
                "active": row["active"],
                "authority_revision": row["authority_revision"],
                "capability_key": row["capability_key"],
                "delegable": row["delegable"],
            }
            for row in rows
        ]
        return materialize_platform_authority(
            principal_id=principal_id,
            rows=normalized_rows,
        )
