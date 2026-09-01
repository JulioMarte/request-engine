"""PostgreSQL party lookup reader (`parties.lookup` query surface).

Lookup semantics:

- `phone`: normalized exact match across active `phone`/`whatsapp` contact
  points; may return many parties (shared family number is expected). A
  party holding the same normalized value on both channels appears exactly
  once (`SELECT DISTINCT`).
- `document`: normalized exact match on `(kind, value)` among active
  identity documents; `document_kind` defaults to `cedula`.
- `name`: case-insensitive, accent-insensitive, whitespace-collapsed prefix
  match. The application layer folds the prefix term (`name_search_key`);
  the SQL side folds the stored name with the same accent map — translate()
  over the accented Latin characters (a e i o u with grave/acute/umlaut/
  circumflex, plus ñ->n and ç->c, lower and upper forms) — and collapses
  whitespace runs with regexp_replace, so stored "José  Pérez" is found by
  prefix "jose perez". The Python and SQL fold maps must stay aligned.

Reads take no locks beyond the tenant RLS context; results are ordered by
display_name and capped at 50 parties.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_registry_views import load_party_views
from request_engine.modules.tenancy.application.queries import lookup_parties
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_LOOKUP_LIMIT = 50


class PostgresPartyLookupReader:
    """Read-only, tenant-scoped party lookup."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def lookup(self, query: lookup_parties.PartyLookupQuery) -> tuple[RegisteredParty, ...]:
        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            if query.mode is lookup_parties.PartyLookupMode.PHONE:
                party_ids = await _match_phone(session, query)
            elif query.mode is lookup_parties.PartyLookupMode.DOCUMENT:
                party_ids = await _match_document(session, query)
            else:
                party_ids = await _match_name_prefix(session, query)
            return tuple(await load_party_views(session, query.organization_id, party_ids))


async def _match_phone(session: AsyncSession, query: lookup_parties.PartyLookupQuery) -> list[UUID]:
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT p.id, p.display_name
            FROM request_engine.parties p
            JOIN request_engine.party_contact_points c
              ON c.organization_id = p.organization_id AND c.party_id = p.id
            WHERE p.organization_id = :organization_id
              AND p.active
              AND c.active
              AND c.channel IN ('phone', 'whatsapp')
              AND c.normalized_value = :value
            ORDER BY p.display_name, p.id
            LIMIT 50
            """
        ),
        {"organization_id": query.organization_id, "value": query.value},
    )
    return list(rows.scalars().all())


async def _match_document(
    session: AsyncSession, query: lookup_parties.PartyLookupQuery
) -> list[UUID]:
    rows = await session.execute(
        text(
            """
            SELECT p.id
            FROM request_engine.parties p
            JOIN request_engine.party_identity_documents d
              ON d.organization_id = p.organization_id AND d.party_id = p.id
            WHERE p.organization_id = :organization_id
              AND p.active
              AND d.active
              AND d.kind = :kind
              AND d.normalized_value = :value
            ORDER BY p.display_name, p.id
            LIMIT 50
            """
        ),
        {
            "organization_id": query.organization_id,
            "kind": query.document_kind,
            "value": query.value,
        },
    )
    return list(rows.scalars().all())


async def _match_name_prefix(
    session: AsyncSession, query: lookup_parties.PartyLookupQuery
) -> list[UUID]:
    rows = await session.execute(
        text(
            """
            SELECT p.id
            FROM request_engine.parties p
            WHERE p.organization_id = :organization_id
              AND p.active
              AND translate(
                    regexp_replace(lower(p.display_name), '\\s+', ' ', 'g'),
                    :accent_from,
                    :accent_to
                  ) LIKE :prefix ESCAPE '\\'
            ORDER BY p.display_name, p.id
            LIMIT 50
            """
        ),
        {
            "organization_id": query.organization_id,
            "prefix": _like_prefix(query.value),
            "accent_from": _ACCENT_FROM,
            "accent_to": _ACCENT_TO,
        },
    )
    return list(rows.scalars().all())


def _like_prefix(search_key: str) -> str:
    escaped = search_key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


_ACCENT_FROM = "áàäâãéèëêíìïîóòöôõúùüûñçÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛÑÇ"
_ACCENT_TO = "aaaaaeeeeiiiiooooouuuuncAAAAAEEEEIIIIOOOOOUUUUNC"
