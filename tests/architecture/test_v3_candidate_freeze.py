from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "docs/release/v3-candidate-freeze.json"
APPLY_SCRIPT = ROOT / "scripts/db/apply_v3_candidate.sh"
FREEZE_PROOF = ROOT / "scripts/release/prove_v3_candidate_freeze.py"
INITIAL_BUILDER = ROOT / "scripts/db/build_v3_initial_candidate.py"


def _apply_order() -> list[str]:
    source = APPLY_SCRIPT.read_text(encoding="utf-8")
    return re.findall(r'^\s*"(\d{3}-[^"]+\.sql)"\s*$', source, flags=re.MULTILINE)


def test_candidate_freeze_locks_the_complete_apply_order() -> None:
    payload = json.loads(FREEZE.read_text(encoding="utf-8"))
    migrations = payload["migrations"]

    assert payload["format_version"] == 1
    assert payload["candidate_source_commit"] == "4311200a8a9d8dfa18340c0eba5dff0cfdb47803"
    assert payload["candidate_source_tree"] == "68b92307d85dca0e30cdcee763e8cf9512fef186"
    assert len(migrations) == 43
    assert [item["name"] for item in migrations] == _apply_order()
    assert all(re.fullmatch(r"[0-9a-f]{40}", item["git_blob_sha1"]) for item in migrations)
    assert len({item["git_blob_sha1"] for item in migrations}) == len(migrations)


def test_candidate_freeze_locks_construction_and_fingerprint_tools() -> None:
    payload = json.loads(FREEZE.read_text(encoding="utf-8"))

    assert payload["apply_script"]["path"] == "scripts/db/apply_v3_candidate.sh"
    assert payload["schema_fingerprint_tool"]["path"] == "scripts/db/v3_schema_fingerprint.py"
    assert re.fullmatch(r"[0-9a-f]{40}", payload["apply_script"]["git_blob_sha1"])
    assert re.fullmatch(r"[0-9a-f]{40}", payload["schema_fingerprint_tool"]["git_blob_sha1"])


def test_initial_construction_is_fail_closed_on_candidate_drift() -> None:
    proof_source = FREEZE_PROOF.read_text(encoding="utf-8")
    builder_source = INITIAL_BUILDER.read_text(encoding="utf-8")

    assert "git hash-object" not in proof_source  # the proof invokes git as argv, never through a shell
    assert '"hash-object"' in proof_source
    assert '"merge-base", "--is-ancestor"' in proof_source
    assert "candidate migration inventory drift" in proof_source
    assert "apply_v3_candidate.sh order no longer matches" in proof_source
    assert "prove_candidate_freeze(args.freeze_output)" in builder_source
    assert "not the final blessed G17 0001_initial" in builder_source
