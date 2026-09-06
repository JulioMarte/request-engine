from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db" / "analyze_schema_cohesion.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schema_cohesion_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _routine(
    name: str,
    *,
    arguments: str = "",
    body: str = "BEGIN RETURN NEW; END",
    security_definer: bool = True,
) -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "routine_name": name,
        "identity_arguments": arguments,
        "routine_kind": "f",
        "owner": "request_engine_schema_owner",
        "security_definer": security_definer,
        "volatility": "v",
        "configuration": ["search_path=pg_catalog, request_engine, pg_temp"],
        "definition": (
            f"CREATE OR REPLACE FUNCTION request_engine.{name}({arguments})\n"
            " RETURNS trigger\n"
            " LANGUAGE plpgsql\n"
            f"AS $function$\n{body}\n$function$\n"
        ),
    }


def _index(name: str, *, primary: bool = False, column: str = "value") -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": "sample",
        "index_name": name,
        "is_unique": False,
        "is_primary": primary,
        "is_valid": True,
        "definition": f"CREATE INDEX {name} ON request_engine.sample USING btree ({column})",
    }


def _relation(name: str, *, rls: bool = False, force_rls: bool = False) -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": name,
        "relation_kind": "r",
        "definition": None,
        "owner": "request_engine_schema_owner",
        "row_security": rls,
        "force_row_security": force_rls,
        "is_partition": False,
    }


def _policy(relation: str, name: str = "tenant_policy") -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": relation,
        "policy_name": name,
        "permissive": "PERMISSIVE",
        "roles": ["public"],
        "cmd": "ALL",
        "qual": "organization_id = request_engine.current_organization_id()",
        "with_check": "organization_id = request_engine.current_organization_id()",
    }


def _grant(
    relation: str,
    privilege: str,
    *,
    grantee: str = "request_engine_app",
    grantable: bool = False,
) -> dict[str, object]:
    return {
        "schema_name": "request_engine",
        "relation_name": relation,
        "grantee": grantee,
        "grantor": "request_engine_schema_owner",
        "privilege_type": privilege,
        "is_grantable": grantable,
    }


def _catalog() -> dict[str, object]:
    return {
        "relations": [],
        "view_dependencies": [],
        "routines": [],
        "indexes": [],
        "triggers": [],
        "policies": [],
        "constraints": [],
        "table_grants": [],
        "column_grants": [],
        "routine_grants": [],
    }


def test_routine_duplicates_ignore_name_but_preserve_contract() -> None:
    module = _load()
    catalog = _catalog()
    catalog["routines"] = [
        _routine("first"),
        _routine("second"),
        _routine("different_arguments", arguments="value uuid"),
        _routine("different_security", security_definer=False),
        _routine("different_body", body="BEGIN RETURN OLD; END"),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["exact_routine_implementation_duplicates"] == [
        ["request_engine.first()", "request_engine.second()"]
    ]


def test_index_duplicates_ignore_only_index_name() -> None:
    module = _load()
    catalog = _catalog()
    catalog["indexes"] = [
        _index("sample_value_a"),
        _index("sample_value_b"),
        _index("sample_other", column="other"),
        _index("sample_primary_shape", primary=True),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["exact_index_definition_duplicates"] == [
        [
            "request_engine.sample.sample_value_a",
            "request_engine.sample.sample_value_b",
        ]
    ]


def test_unreferenced_trigger_routines_are_review_candidates() -> None:
    module = _load()
    catalog = _catalog()
    catalog["routines"] = [_routine("used"), _routine("unused")]
    catalog["triggers"] = [
        {
            "schema_name": "request_engine",
            "relation_name": "sample",
            "trigger_name": "sample_used",
            "enabled": "O",
            "definition": (
                "CREATE TRIGGER sample_used AFTER UPDATE ON request_engine.sample "
                "FOR EACH ROW EXECUTE FUNCTION request_engine.used()"
            ),
        }
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["trigger_routine_count"] == 2
    assert result["referenced_trigger_routine_count"] == 1
    assert result["unreferenced_trigger_routines"] == ["request_engine.unused()"]


def test_rls_analysis_surfaces_missing_and_misplaced_policies() -> None:
    module = _load()
    catalog = _catalog()
    catalog["relations"] = [
        _relation("protected", rls=True, force_rls=True),
        _relation("missing", rls=True),
        _relation("plain"),
    ]
    catalog["policies"] = [
        _policy("protected"),
        _policy("protected", "internal_writer"),
        _policy("plain"),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["rls_relation_count"] == 2
    assert result["force_rls_relation_count"] == 1
    assert result["policy_count"] == 3
    assert result["rls_relations_without_policy"] == ["request_engine.missing"]
    assert result["policies_on_non_rls_relations"] == [
        "request_engine.plain.tenant_policy"
    ]
    assert result["multi_policy_relations"] == [
        {
            "relation": "request_engine.protected",
            "policies": [
                "request_engine.protected.internal_writer",
                "request_engine.protected.tenant_policy",
            ],
        }
    ]


def test_grant_analysis_surfaces_public_grantable_and_immutable_mutation_authority() -> None:
    module = _load()
    catalog = _catalog()
    catalog["relations"] = [_relation("immutable")]
    catalog["triggers"] = [
        {
            "schema_name": "request_engine",
            "relation_name": "immutable",
            "trigger_name": "immutable_append_only",
            "enabled": "O",
            "definition": (
                "CREATE TRIGGER immutable_append_only BEFORE UPDATE OR DELETE "
                "ON request_engine.immutable FOR EACH ROW "
                "EXECUTE FUNCTION request_engine.reject_immutable_mutation()"
            ),
        }
    ]
    catalog["table_grants"] = [
        _grant("immutable", "UPDATE"),
        _grant("immutable", "SELECT", grantee="PUBLIC"),
        _grant("immutable", "INSERT", grantee="request_engine_admin", grantable=True),
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["public_grants"] == [
        "table:request_engine.immutable:PUBLIC:SELECT"
    ]
    assert result["grantable_grants"] == [
        "table:request_engine.immutable:request_engine_admin:INSERT"
    ]
    assert result["immutable_app_mutation_grants"] == [
        "table:request_engine.immutable:request_engine_app:UPDATE"
    ]


def test_invalid_indexes_and_unvalidated_constraints_are_reported() -> None:
    module = _load()
    catalog = _catalog()
    invalid = _index("invalid")
    invalid["is_valid"] = False
    catalog["indexes"] = [invalid]
    catalog["constraints"] = [
        {
            "schema_name": "request_engine",
            "relation_name": "sample",
            "constraint_name": "sample_check",
            "constraint_type": "c",
            "definition": "CHECK (value > 0)",
            "validated": False,
        }
    ]

    result = cast(dict[str, object], module.analyze(catalog))

    assert result["invalid_indexes"] == ["request_engine.sample.invalid"]
    assert result["unvalidated_constraints"] == [
        "request_engine.sample.sample_check"
    ]
