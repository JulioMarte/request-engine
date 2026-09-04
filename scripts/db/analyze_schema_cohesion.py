from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
_VERSIONED = re.compile(r"^(?P<family>.+)_v(?P<version>[0-9]+)$")


def _dict_rows(payload: dict[str, object], key: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], payload.get(key, []))


def _production_references(name: str) -> list[str]:
    references: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if name in path.read_text(encoding="utf-8"):
            references.append(path.relative_to(ROOT).as_posix())
    return references


def _view_rows(catalog: dict[str, object]) -> list[dict[str, Any]]:
    return [row for row in _dict_rows(catalog, "relations") if row["relation_kind"] in ("v", "m")]


def _view_dependents(catalog: dict[str, object]) -> dict[tuple[str, str], list[str]]:
    dependents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in _dict_rows(catalog, "view_dependencies"):
        source = (str(edge["source_schema"]), str(edge["source_relation"]))
        dependent = f"{edge['view_schema']}.{edge['view_name']}"
        dependents[source].add(dependent)
    return {key: sorted(values) for key, values in dependents.items()}


def _version(row: dict[str, object]) -> int:
    return cast(int, row["version"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive review candidates from a schema catalog")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw_catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    catalog = cast(dict[str, object], raw_catalog)
    views = _view_rows(catalog)
    view_dependents = _view_dependents(catalog)

    families: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    duplicate_definitions: dict[str, list[str]] = defaultdict(list)
    view_usage: list[dict[str, object]] = []

    for view in views:
        schema = str(view["schema_name"])
        name = str(view["relation_name"])
        definition = cast(str | None, view.get("definition"))
        match = _VERSIONED.match(name)
        if match:
            families[(schema, match.group("family"))].append(
                {"name": name, "version": int(match.group("version"))}
            )
        if definition:
            duplicate_definitions[definition].append(f"{schema}.{name}")
        references = _production_references(name)
        database_dependents = view_dependents.get((schema, name), [])
        view_usage.append(
            {
                "view": f"{schema}.{name}",
                "production_references": references,
                "production_reference_count": len(references),
                "database_view_dependents": database_dependents,
                "database_view_dependent_count": len(database_dependents),
            }
        )

    version_families = [
        {
            "schema": schema,
            "family": family,
            "members": sorted(members, key=_version),
        }
        for (schema, family), members in sorted(families.items())
        if len(members) > 1
    ]
    exact_view_duplicates = [
        sorted(names) for names in duplicate_definitions.values() if len(names) > 1
    ]
    zero_reference_views = sorted(
        cast(str, row["view"])
        for row in view_usage
        if cast(int, row["production_reference_count"]) == 0
    )
    orphan_view_candidates = sorted(
        cast(str, row["view"])
        for row in view_usage
        if cast(int, row["production_reference_count"]) == 0
        and cast(int, row["database_view_dependent_count"]) == 0
    )

    result = {
        "schema_version": 2,
        "view_count": len(views),
        "version_families": version_families,
        "exact_view_definition_duplicates": sorted(exact_view_duplicates),
        "zero_production_reference_views": zero_reference_views,
        "orphan_view_candidates": orphan_view_candidates,
        "view_usage": sorted(view_usage, key=lambda row: cast(str, row["view"])),
        "note": (
            "Orphan candidates have no Python production reference and no dependent view. "
            "They are review candidates, not automatic deletion decisions; routine bodies, "
            "grants, external SQL callers and published contracts still apply."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
