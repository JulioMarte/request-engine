"""Write migrations/baseline/manifest.json for the 0047 rebaseline (transitional).

Inputs are the cluster-A (historical head 0047) evidence produced by
build_rebaseline_0047_candidate.py and the catalog exporters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "migrations" / "baseline"
CORE = ("request_engine_", "request_platform_", "request_bootstrap_")
_EMPTY_FINDINGS = (
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


def _file(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    ev = args.evidence

    summary = _load(ev / "payload-summary.json")
    schema = _load(ev / "head-a-schema-catalog.json")
    roles = _load(ev / "head-a-role-catalog.json")
    seed_path = ev / "head-a-seed-data-catalog.json"
    shutil.copyfile(seed_path, BASELINE / "seed-data-catalog.json")
    seed = _load(seed_path)

    def attrs(role: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in role.items() if key != "role_name"}

    core = {r["role_name"]: attrs(r) for r in roles["roles"] if r["role_name"].startswith(CORE)}
    extension = {
        r["role_name"]: attrs(r) for r in roles["roles"] if not r["role_name"].startswith(CORE)
    }
    if roles["role_memberships"] or roles["role_settings"]:
        raise SystemExit("source cluster has role memberships/settings; review required")

    tables = sum(1 for r in schema["relations"] if r["relation_kind"] in {"r", "p"})
    views = sum(1 for r in schema["relations"] if r["relation_kind"] in {"v", "m"})
    counts = schema["counts"]
    manifest = {
        "schema_version": 1,
        "source": {
            "branch": "tmp/rebaseline-0047",
            "head_sha": args.source_sha,
            "postgresql_version": "18.6",
            "pg_dump_version": summary["pg_dump_version"],
            "source_alembic_head": "0047_reservation_calendar_read",
            "collapsed_history": "0001_initial(0094 baseline)+0002..0047",
            "rebaseline_date": "2026-10-23",
        },
        "schema_payload": {
            "bytes": summary["bytes"],
            "sha256": summary["sha256"],
            "materialized_parts": summary["materialized_parts"],
            "source_artifact": {
                "name": "rebaseline-0047/source-full-dump.sql",
                **summary["source_artifact"],
            },
            "canonicalization": {
                "reason": (
                    "installation-local identity must be generated independently for every "
                    "fresh installation"
                ),
                "changes": [
                    "built-in native/workload identity-authority UUIDs use table defaults "
                    "instead of copied source values",
                    "platform_instance references the freshly generated built-in authorities",
                    "installation-local creation timestamps use PostgreSQL defaults instead "
                    "of copied source timestamps",
                    "COMMENT ON EXTENSION is omitted because CREATE EXTENSION recreates the "
                    "extension's own comment",
                    "four leftmost length(x) >= a AND length(x) <= b CHECK conjuncts are "
                    "restored to their original BETWEEN source form so replay reproduces the "
                    "exact stored expression tree",
                ],
                "ddl_changed": False,
                "schema_only_pg_dump_byte_identical_to_source": True,
            },
        },
        "role_bootstrap": {
            **_file(BASELINE / "0001_roles.sql"),
            "expected_roles": core,
            "role_memberships": [],
            "role_settings": [],
            "extension_roles": {
                **_file(BASELINE / "0001_extension_roles.sql"),
                "expected_roles": extension,
            },
            "post_install_audit": _file(BASELINE / "0001_post_install_audit.sql"),
        },
        "seed_data": {
            **_file(BASELINE / "seed-data-catalog.json"),
            "counts": seed["counts"],
            "representation": "semantic-normalized",
            "normalized_fresh_install_fields": [
                "request_engine.identity_authorities.id for built-in native/workload authorities",
                "request_engine.identity_authorities.created_at for built-in native/workload "
                "authorities",
                "request_engine.platform_instance.id",
                "request_engine.platform_instance.created_at",
                "request_engine.platform_instance built-in authority foreign keys",
            ],
        },
        "effective_model": {
            "relations": counts["relations"],
            "tables": tables,
            "views": views,
            "columns": counts["columns"],
            "constraints": counts["constraints"],
            "indexes": counts["indexes"],
            "routines": counts["routines"],
            "triggers": counts["triggers"],
            "policies": counts["policies"],
            "roles": len(core) + len(extension),
            "role_memberships": 0,
            "column_grants": counts["column_grants"],
        },
        "accepted_analyzer_findings": {
            name: value
            for name, value in _load(ev / "head-a-schema-cohesion.json").items()
            if name in _EMPTY_FINDINGS and value
        },
        "accepted_analyzer_findings_disposition": {
            "exact_index_definition_duplicates": (
                "KEEP in the collapse: staff_memberships_org_id_unique (historical 0011) "
                "duplicates staff_memberships_org_id_uq (historical 0009); both foreign keys "
                "use _uq. Removal is ordinary 0002+ schema evolution, not part of a history "
                "collapse."
            )
        },
        "proof": {
            "historical_chain_to_0047": True,
            "independent_clean_cluster_reproduction": (
                "docs/audits/postgresql-rebaseline-0047.md"
            ),
        },
        "installation_identity": {
            "generated_per_fresh_install": True,
            "platform_instance_id": "gen_random_uuid()",
            "built_in_authority_ids": "gen_random_uuid()",
            "created_at": "clock_timestamp()",
            "proof_requirement": (
                "two clean 0001 installations must have distinct platform/native/workload UUIDs"
            ),
        },
    }
    (BASELINE / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(manifest["effective_model"]))


if __name__ == "__main__":
    main()
