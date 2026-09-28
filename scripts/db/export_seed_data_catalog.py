from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

SCHEMAS = ("request_admin", "request_auth", "request_cmd", "request_engine", "request_platform", "request_read")


def _relations(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return [(str(row[0]), str(row[1])) for row in conn.execute(
        """SELECT n.nspname, c.relname FROM pg_class AS c
           JOIN pg_namespace AS n ON n.oid = c.relnamespace
           WHERE n.nspname = ANY(%s) AND c.relkind = 'r' ORDER BY 1, 2""",
        (list(SCHEMAS),),
    ).fetchall()]


def _sequences(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    return [(str(row[0]), str(row[1])) for row in conn.execute(
        """SELECT n.nspname, c.relname FROM pg_class AS c
           JOIN pg_namespace AS n ON n.oid = c.relnamespace
           WHERE n.nspname = ANY(%s) AND c.relkind = 'S' ORDER BY 1, 2""",
        (list(SCHEMAS),),
    ).fetchall()]


def _normalize_seed_row(schema_name: str, relation_name: str, raw: str) -> str:
    """Normalize only fields that are intentionally unique to each fresh installation."""
    if schema_name != "request_engine":
        return raw
    value = json.loads(raw)
    if relation_name == "identity_authorities":
        shape = (value.get("kind"), value.get("issuer_or_environment"), value.get("status"),
                 value.get("revision"), value.get("configuration_ref"))
        if shape == ("native", "request-engine-native", "active", 1, None):
            value["id"] = "<generated:built-in-native-authority-id>"
            value["created_at"] = "<generated:created-at>"
        elif shape == ("workload", "request-engine-workload", "active", 1, None):
            value["id"] = "<generated:built-in-workload-authority-id>"
            value["created_at"] = "<generated:created-at>"
        else:
            return raw
    elif relation_name == "platform_instance":
        shape = (value.get("singleton_key"), value.get("state"), value.get("revision"),
                 value.get("claimed_at"), value.get("initial_owner_principal_id"),
                 value.get("claim_provenance"))
        if shape != (1, "unclaimed", 1, None, None, None):
            return raw
        value["id"] = "<generated:platform-instance-id>"
        value["built_in_native_authority_id"] = "<generated:built-in-native-authority-id>"
        value["built_in_workload_authority_id"] = "<generated:built-in-workload-authority-id>"
        value["created_at"] = "<generated:created-at>"
    else:
        return raw
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def export(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    total_rows = 0
    for schema_name, relation_name in _relations(conn):
        query = sql.SQL("SELECT to_jsonb(t)::text FROM {}.{} AS t").format(
            sql.Identifier(schema_name), sql.Identifier(relation_name))
        rows = sorted(_normalize_seed_row(schema_name, relation_name, str(row[0]))
                      for row in conn.execute(query).fetchall())
        total_rows += len(rows)
        tables.append({"schema_name": schema_name, "relation_name": relation_name,
                       "row_count": len(rows), "rows": rows})
    sequences: list[dict[str, Any]] = []
    for schema_name, sequence_name in _sequences(conn):
        query = sql.SQL("SELECT last_value::text, is_called FROM {}.{}").format(
            sql.Identifier(schema_name), sql.Identifier(sequence_name))
        row = conn.execute(query).fetchone()
        if row is None:
            raise RuntimeError(f"sequence state unavailable: {schema_name}.{sequence_name}")
        sequences.append({"schema_name": schema_name, "sequence_name": sequence_name,
                          "last_value": str(row[0]), "is_called": bool(row[1])})
    return {"schema_version": 1, "schemas": list(SCHEMAS),
            "counts": {"tables": len(tables),
                       "nonempty_tables": sum(1 for table in tables if table["row_count"]),
                       "rows": total_rows, "sequences": len(sequences)},
            "tables": tables, "sequences": sequences}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export deterministic migration-owned seed/reference state")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with psycopg.connect("") as conn:
        payload = export(conn)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
