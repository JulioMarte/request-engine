from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from . import operational_support as support


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    """Content fingerprints for every authoritative table, not merely row counts."""

    tables: tuple[tuple[str, int, str], ...]


def durable_snapshot(conn: support.PgConnection) -> DurableSnapshot:
    rows = conn.execute(
        """
        SELECT c.relname
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
        """
    ).fetchall()
    fingerprints: list[tuple[str, int, str]] = []
    for (raw_table_name,) in rows:
        table_name = str(raw_table_name)
        row = conn.execute(
            sql.SQL(
                """
                SELECT count(*)::bigint,
                       md5(COALESCE(
                           jsonb_agg(to_jsonb(snapshot_row)
                               ORDER BY to_jsonb(snapshot_row)::text)::text,
                           '[]'
                       ))
                FROM {} AS snapshot_row
                """
            ).format(sql.Identifier("request_engine", table_name))
        ).fetchone()
        assert row is not None
        fingerprints.append((table_name, int(row[0]), str(row[1])))
    return DurableSnapshot(tuple(fingerprints))
