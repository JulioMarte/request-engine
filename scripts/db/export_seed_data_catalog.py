from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

SCHEMAS = (
    "request_admin",
    "request_auth",
    "request_cmd",
    "request_engine",
    "request_platform",
    "request_read",
)


def _relations(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            """
            SELECT n.nspname, c.relname
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = ANY(%s)
               AND c.relkind = 'r'
             ORDER BY 1, 2
            """,
            (list(SCHEMAS),),
        ).fetchall()
    ]


def _sequences(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            """
            SELECT n.nspname, c.relname
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = ANY(%s)
               AND c.relkind = 'S'
             ORDER BY 1, 2
            """,
            (list(SCHEMAS),),
        ).fetchall()
    ]


def export(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    total_rows = 0
    for schema_name, relation_name in _relations(conn):
        query = sql.SQL("SELECT to_jsonb(t)::text FROM {}.{} AS t").format(
            sql.Identifier(schema_name),
            sql.Identifier(relation_name),
        )
        rows = sorted(str(row[0]) for row in conn.execute(query).fetchall())
        total_rows += len(rows)
        tables.append(
            {
                "schema_name": schema_name,
                "relation_name": relation_name,
                "row_count": len(rows),
                "rows": rows,
            }
        )

    sequences: list[dict[str, Any]] = []
    for schema_name, sequence_name in _sequences(conn):
        query = sql.SQL("SELECT last_value::text, is_called FROM {}.{}").format(
            sql.Identifier(schema_name),
            sql.Identifier(sequence_name),
        )
        row = conn.execute(query).fetchone()
        if row is None:
            raise RuntimeError(f"sequence state unavailable: {schema_name}.{sequence_name}")
        sequences.append(
            {
                "schema_name": schema_name,
                "sequence_name": sequence_name,
                "last_value": str(row[0]),
                "is_called": bool(row[1]),
            }
        )

    nonempty_tables = sum(1 for table in tables if table["row_count"])
    return {
        "schema_version": 1,
        "schemas": list(SCHEMAS),
        "counts": {
            "tables": len(tables),
            "nonempty_tables": nonempty_tables,
            "rows": total_rows,
            "sequences": len(sequences),
        },
        "tables": tables,
        "sequences": sequences,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export deterministic migration-owned seed/reference state"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with psycopg.connect("") as conn:
        payload = export(conn)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
