from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
_VERSIONED = re.compile(r"^(?P<family>.+)_v(?P<version>[0-9]+)$")


def _rows(payload: dict[str, object], key: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], payload.get(key, []))


def _production_references(name: str) -> list[str]:
    references: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if name in path.read_text(encoding="utf-8"):
            references.append(path.relative_to(ROOT).as_posix())
    return references


def _view_dependents(catalog: dict[str, object]) -> dict[tuple[str, str], list[str]]:
    dependents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in _rows(catalog, "view_dependencies"):
        key = (str(edge["source_schema"]), str(edge["source_relation"]))
        dependents[key].add(f"{edge['view_schema']}.{edge['view_name']}")
    return {key: sorted(values) for key, values in dependents.items()}


def _security_findings(catalog: dict[str, object]) -> dict[str, object]:
    routines = _rows(catalog, "routines")
    definers = [row for row in routines if bool(row["security_definer"])]
    unsafe_path = [
        f"{row['schema_name']}.{row['routine_name']}({row['identity_arguments']})"
        for row in definers
        if not any(str(item).startswith("search_path=") for item in (row.get("configuration") or []))
    ]
    public_execute = sorted(
        f"{row['schema_name']}.{row['routine_name']}({row['identity_arguments']})"
        for row in _rows(catalog, "routine_grants")
        if row["grantee"] == "PUBLIC" and row["privilege_type"] == "EXECUTE"
    )
    return {
        "security_definer_count": len(definers),
        "security_definer_without_search_path": unsafe_path,
        "public_execute_routines": public_execute,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive schema-cohesion review candidates")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = cast(dict[str, object], json.loads(args.catalog.read_text(encoding="utf-8")))
    views = [row for row in _rows(catalog, "relations") if row["relation_kind"] in ("v", "m")]
    dependents = _view_dependents(catalog)
    families: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    definitions: dict[str, list[str]] = defaultdict(list)
    usage: list[dict[str, object]] = []
    for view in views:
        schema, name = str(view["schema_name"]), str(view["relation_name"])
        match = _VERSIONED.match(name)
        if match:
            families[(schema, match.group("family"))].append(
                {"name": name, "version": int(match.group("version"))}
            )
        if view.get("definition"):
            definitions[str(view["definition"])].append(f"{schema}.{name}")
        refs = _production_references(name)
        db_refs = dependents.get((schema, name), [])
        usage.append({"view": f"{schema}.{name}", "production_references": refs,
                      "production_reference_count": len(refs), "database_view_dependents": db_refs,
                      "database_view_dependent_count": len(db_refs)})
    result = {
        "schema_version": 1,
        "view_count": len(views),
        "version_families": [
            {"schema": schema, "family": family, "members": sorted(members, key=lambda row: cast(int, row["version"]))}
            for (schema, family), members in sorted(families.items()) if len(members) > 1
        ],
        "exact_view_definition_duplicates": sorted(sorted(names) for names in definitions.values() if len(names) > 1),
        "orphan_view_candidates": sorted(cast(str, row["view"]) for row in usage
                                         if row["production_reference_count"] == 0 and row["database_view_dependent_count"] == 0),
        "view_usage": sorted(usage, key=lambda row: cast(str, row["view"])),
        "security": _security_findings(catalog),
        "note": "Candidates require semantic review; absence of Python references alone never authorizes deletion.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
