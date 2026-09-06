from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
_VERSIONED = re.compile(r"^(?P<family>.+)_v(?P<version>[0-9]+)$")
_TRIGGER_CALL = re.compile(r"EXECUTE FUNCTION (?P<routine>[^\s(]+)\(")


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


def _routine_label(row: dict[str, Any]) -> str:
    return f"{row['schema_name']}.{row['routine_name']}({row['identity_arguments']})"


def _routine_implementation_signature(row: dict[str, Any]) -> tuple[object, ...]:
    definition = str(row["definition"])
    _declaration, separator, implementation = definition.partition("\n")
    return (
        row["routine_kind"],
        row["identity_arguments"],
        row["security_definer"],
        row["volatility"],
        tuple(row.get("configuration") or ()),
        implementation if separator else definition,
    )


def _exact_routine_duplicates(catalog: dict[str, object]) -> list[list[str]]:
    groups: dict[tuple[object, ...], list[str]] = defaultdict(list)
    for routine in _dict_rows(catalog, "routines"):
        groups[_routine_implementation_signature(routine)].append(_routine_label(routine))
    return sorted(sorted(names) for names in groups.values() if len(names) > 1)


def _index_signature(row: dict[str, Any]) -> tuple[object, ...]:
    definition = str(row["definition"])
    _declaration, separator, on_clause = definition.partition(" ON ")
    structural_definition = f"ON {on_clause}" if separator else definition
    return (
        row["schema_name"],
        row["relation_name"],
        row["is_unique"],
        row["is_primary"],
        row["is_valid"],
        structural_definition,
    )


def _exact_index_duplicates(catalog: dict[str, object]) -> list[list[str]]:
    groups: dict[tuple[object, ...], list[str]] = defaultdict(list)
    for index in _dict_rows(catalog, "indexes"):
        groups[_index_signature(index)].append(
            f"{index['schema_name']}.{index['relation_name']}.{index['index_name']}"
        )
    return sorted(sorted(names) for names in groups.values() if len(names) > 1)


def _trigger_routine_names(catalog: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for trigger in _dict_rows(catalog, "triggers"):
        match = _TRIGGER_CALL.search(str(trigger["definition"]))
        if match:
            names.add(match.group("routine"))
    return names


def _trigger_routines(catalog: dict[str, object]) -> list[dict[str, Any]]:
    return [
        routine
        for routine in _dict_rows(catalog, "routines")
        if "RETURNS trigger" in str(routine["definition"])
    ]


def _unreferenced_trigger_routines(catalog: dict[str, object]) -> list[str]:
    referenced = _trigger_routine_names(catalog)
    return sorted(
        _routine_label(routine)
        for routine in _trigger_routines(catalog)
        if f"{routine['schema_name']}.{routine['routine_name']}" not in referenced
    )


def _relation_label(row: dict[str, Any]) -> str:
    return f"{row['schema_name']}.{row['relation_name']}"


def _policy_label(row: dict[str, Any]) -> str:
    return f"{row['schema_name']}.{row['relation_name']}.{row['policy_name']}"


def _rls_analysis(catalog: dict[str, object]) -> dict[str, object]:
    relations = _dict_rows(catalog, "relations")
    policies = _dict_rows(catalog, "policies")
    relation_by_key = {
        (str(row["schema_name"]), str(row["relation_name"])): row for row in relations
    }
    policy_keys: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for policy in policies:
        policy_keys[(str(policy["schema_name"]), str(policy["relation_name"]))].append(policy)

    rls_relations = [row for row in relations if bool(row.get("row_security"))]
    rls_without_policy = sorted(
        _relation_label(row)
        for row in rls_relations
        if (str(row["schema_name"]), str(row["relation_name"])) not in policy_keys
    )
    policies_on_non_rls = sorted(
        _policy_label(policy)
        for policy in policies
        if not bool(
            relation_by_key.get((str(policy["schema_name"]), str(policy["relation_name"])), {}).get(
                "row_security"
            )
        )
    )
    multi_policy_relations = [
        {
            "relation": f"{schema}.{relation}",
            "policies": sorted(_policy_label(policy) for policy in relation_policies),
        }
        for (schema, relation), relation_policies in sorted(policy_keys.items())
        if len(relation_policies) > 1
    ]
    return {
        "rls_relation_count": len(rls_relations),
        "force_rls_relation_count": sum(
            1 for row in rls_relations if bool(row.get("force_row_security"))
        ),
        "policy_count": len(policies),
        "rls_relations_without_policy": rls_without_policy,
        "policies_on_non_rls_relations": policies_on_non_rls,
        "multi_policy_relations": multi_policy_relations,
    }


def _grant_label(kind: str, row: dict[str, Any]) -> str:
    schema = row["schema_name"]
    relation = row.get("relation_name")
    routine = row.get("routine_name")
    column = row.get("column_name")
    target = relation or routine
    if column is not None:
        target = f"{target}.{column}"
    return f"{kind}:{schema}.{target}:{row['grantee']}:{row['privilege_type']}"


def _grant_analysis(catalog: dict[str, object]) -> dict[str, object]:
    collections = (
        ("table", _dict_rows(catalog, "table_grants")),
        ("column", _dict_rows(catalog, "column_grants")),
        ("routine", _dict_rows(catalog, "routine_grants")),
    )
    public_grants: list[str] = []
    grantable_grants: list[str] = []
    for kind, rows in collections:
        for row in rows:
            if str(row["grantee"]).upper() == "PUBLIC":
                public_grants.append(_grant_label(kind, row))
            if bool(row.get("is_grantable")):
                grantable_grants.append(_grant_label(kind, row))
    return {
        "public_grants": sorted(public_grants),
        "grantable_grants": sorted(grantable_grants),
    }


def _invalid_indexes(catalog: dict[str, object]) -> list[str]:
    return sorted(
        f"{row['schema_name']}.{row['relation_name']}.{row['index_name']}"
        for row in _dict_rows(catalog, "indexes")
        if not bool(row.get("is_valid"))
    )


def _unvalidated_constraints(catalog: dict[str, object]) -> list[str]:
    return sorted(
        f"{row['schema_name']}.{row['relation_name']}.{row['constraint_name']}"
        for row in _dict_rows(catalog, "constraints")
        if not bool(row.get("validated"))
    )


def _immutable_relations(catalog: dict[str, object]) -> set[tuple[str, str]]:
    return {
        (str(trigger["schema_name"]), str(trigger["relation_name"]))
        for trigger in _dict_rows(catalog, "triggers")
        if "reject_immutable_mutation()" in str(trigger["definition"])
    }


def _immutable_app_mutation_grants(catalog: dict[str, object]) -> list[str]:
    immutable = _immutable_relations(catalog)
    return sorted(
        _grant_label("table", grant)
        for grant in _dict_rows(catalog, "table_grants")
        if grant["grantee"] == "request_engine_app"
        and grant["privilege_type"] in {"UPDATE", "DELETE"}
        and (str(grant["schema_name"]), str(grant["relation_name"])) in immutable
    )


def analyze(catalog: dict[str, object]) -> dict[str, object]:
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
        {"schema": schema, "family": family, "members": sorted(members, key=_version)}
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
    trigger_routines = _trigger_routines(catalog)
    referenced_trigger_routines = _trigger_routine_names(catalog)

    result: dict[str, object] = {
        "schema_version": 4,
        "view_count": len(views),
        "version_families": version_families,
        "exact_view_definition_duplicates": sorted(exact_view_duplicates),
        "zero_production_reference_views": zero_reference_views,
        "orphan_view_candidates": orphan_view_candidates,
        "view_usage": sorted(view_usage, key=lambda row: cast(str, row["view"])),
        "exact_routine_implementation_duplicates": _exact_routine_duplicates(catalog),
        "exact_index_definition_duplicates": _exact_index_duplicates(catalog),
        "trigger_routine_count": len(trigger_routines),
        "referenced_trigger_routine_count": len(referenced_trigger_routines),
        "unreferenced_trigger_routines": _unreferenced_trigger_routines(catalog),
        "invalid_indexes": _invalid_indexes(catalog),
        "unvalidated_constraints": _unvalidated_constraints(catalog),
        "immutable_app_mutation_grants": _immutable_app_mutation_grants(catalog),
        "note": (
            "All duplicate/orphan outputs are review candidates, not automatic deletion decisions. "
            "Routine comparison ignores only the declared routine name while preserving signature, "
            "security, volatility, configuration and implementation. Index comparison ignores only "
            "the index name. RLS/grant outputs identify structural authority anomalies, not "
            "business authorization by themselves. External SQL callers and published contracts "
            "still require review."
        ),
    }
    result.update(_rls_analysis(catalog))
    result.update(_grant_analysis(catalog))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive review candidates from a schema catalog")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw_catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    result = analyze(cast(dict[str, object], raw_catalog))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
