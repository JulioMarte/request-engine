from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "migrations" / "baseline" / "manifest.json"

_EMPTY_ANALYZER_FINDINGS = (
    "exact_view_definition_duplicates",
    "exact_routine_implementation_duplicates",
    "exact_index_definition_duplicates",
    "unreferenced_trigger_routines",
    "invalid_indexes",
    "unvalidated_constraints",
    "public_grants",
    "grantable_grants",
    "immutable_app_mutation_grants",
    "rls_relations_without_policy",
    "policies_on_non_rls_relations",
    "version_families",
    "orphan_view_candidates",
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _relation_counts(catalog: dict[str, Any]) -> tuple[int, int]:
    tables = 0
    views = 0
    for relation in catalog["relations"]:
        kind = relation["relation_kind"]
        if kind in {"r", "p"}:
            tables += 1
        elif kind in {"v", "m"}:
            views += 1
    return tables, views


def verify(
    *,
    manifest: dict[str, Any],
    schema_catalog: dict[str, Any],
    role_catalog: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    expected = manifest["effective_model"]
    counts = schema_catalog["counts"]
    tables, views = _relation_counts(schema_catalog)

    actual_model = {
        "relations": counts["relations"],
        "tables": tables,
        "views": views,
        "columns": counts["columns"],
        "constraints": counts["constraints"],
        "indexes": counts["indexes"],
        "routines": counts["routines"],
        "triggers": counts["triggers"],
        "policies": counts["policies"],
        "roles": role_catalog["counts"]["roles"],
        "role_memberships": role_catalog["counts"]["role_memberships"],
        "column_grants": counts["column_grants"],
    }
    if actual_model != expected:
        raise RuntimeError(
            "accepted baseline effective-model counts drifted: "
            f"expected={expected!r} actual={actual_model!r}"
        )

    expected_roles = manifest["role_bootstrap"]["expected_roles"]
    actual_roles = {
        role["role_name"]: {key: value for key, value in role.items() if key != "role_name"}
        for role in role_catalog["roles"]
    }
    if actual_roles != expected_roles:
        raise RuntimeError("accepted baseline role topology drifted")
    if role_catalog["role_memberships"] != manifest["role_bootstrap"]["role_memberships"]:
        raise RuntimeError("accepted baseline role memberships drifted")
    if role_catalog["role_settings"] != manifest["role_bootstrap"]["role_settings"]:
        raise RuntimeError("accepted baseline role settings drifted")

    nonempty = {name: analysis.get(name) for name in _EMPTY_ANALYZER_FINDINGS if analysis.get(name)}
    if nonempty:
        raise RuntimeError(f"accepted baseline cohesion findings are no longer empty: {nonempty!r}")

    return {
        "schema_equivalent": True,
        "role_equivalent": True,
        "effective_model": actual_model,
        "analyzer_anomalies": {},
        "baseline_revision": "0001_initial",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the accepted Request Engine 0001 baseline independently "
            "of the current Alembic head."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema-catalog", type=Path, required=True)
    parser.add_argument("--role-catalog", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = verify(
        manifest=_load(args.manifest),
        schema_catalog=_load(args.schema_catalog),
        role_catalog=_load(args.role_catalog),
        analysis=_load(args.analysis),
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        args.output.write_text(payload, encoding="utf-8")
    print("accepted baseline integrity: PASS")


if __name__ == "__main__":
    main()
