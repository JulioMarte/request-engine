#!/usr/bin/env python3
"""Prove the current V3 candidate still matches the explicit post-G19 freeze lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
LOCK_PATH: Final = REPO_ROOT / "docs/release/v3-candidate-freeze.json"
_APPLY_ENTRY_RE: Final = re.compile(r'^\s*"([0-9]{3}-[^"]+\.sql)"\s*$')


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob(path: Path) -> str:
    return _git("hash-object", path.relative_to(REPO_ROOT).as_posix())


def _source_blob(source_commit: str, relative_path: str) -> str:
    output = _git("ls-tree", source_commit, "--", relative_path)
    if not output:
        raise RuntimeError(f"{relative_path} is absent from frozen source {source_commit}")
    metadata, _name = output.split("\t", 1)
    parts = metadata.split()
    if len(parts) != 3 or parts[1] != "blob":
        raise RuntimeError(f"unexpected git tree entry for {relative_path}: {output}")
    return parts[2]


def _apply_order(path: Path) -> list[str]:
    names: list[str] = []
    in_files = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "files=(":
            in_files = True
            continue
        if in_files and stripped == ")":
            break
        if in_files:
            match = _APPLY_ENTRY_RE.match(line)
            if match:
                names.append(match.group(1))
    return names


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []

    source_commit = str(lock["candidate_source_commit"])
    expected_source_tree = str(lock["candidate_source_tree"])
    candidate_dir = REPO_ROOT / str(lock["candidate_directory"])
    expected_migrations = list(lock["migrations"])
    expected_names = [str(item["name"]) for item in expected_migrations]

    current_head = _git("rev-parse", "HEAD")
    current_tree = _git("rev-parse", "HEAD^{tree}")
    source_tree = _git("rev-parse", f"{source_commit}^{{tree}}")
    if source_tree != expected_source_tree:
        failures.append(
            f"frozen source tree mismatch: lock={expected_source_tree} git={source_tree}"
        )

    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestry.returncode != 0:
        failures.append(f"frozen candidate source {source_commit} is not an ancestor of HEAD")

    actual_names = sorted(path.name for path in candidate_dir.glob("*.sql"))
    if actual_names != sorted(expected_names):
        missing = sorted(set(expected_names) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(expected_names))
        failures.append(f"candidate migration inventory drift: missing={missing} unexpected={unexpected}")

    apply_info = lock["apply_script"]
    apply_path = REPO_ROOT / str(apply_info["path"])
    apply_order = _apply_order(apply_path)
    if apply_order != expected_names:
        failures.append("apply_v3_candidate.sh order no longer matches the frozen migration order")

    locked_files = [apply_info, lock["schema_fingerprint_tool"]]
    tool_payload: list[dict[str, str]] = []
    for info in locked_files:
        relative_path = str(info["path"])
        path = REPO_ROOT / relative_path
        expected_blob = str(info["git_blob_sha1"])
        current_blob = _git_blob(path)
        source_blob = _source_blob(source_commit, relative_path)
        if source_blob != expected_blob:
            failures.append(
                f"frozen source blob mismatch for {relative_path}: lock={expected_blob} source={source_blob}"
            )
        if current_blob != expected_blob:
            failures.append(
                f"frozen tool drift for {relative_path}: expected={expected_blob} current={current_blob}"
            )
        tool_payload.append(
            {
                "path": relative_path,
                "git_blob_sha1": current_blob,
                "sha256": _sha256(path),
            }
        )

    migration_payload: list[dict[str, str]] = []
    for item in expected_migrations:
        name = str(item["name"])
        relative_path = f"{lock['candidate_directory']}/{name}"
        path = REPO_ROOT / relative_path
        expected_blob = str(item["git_blob_sha1"])
        if not path.is_file():
            failures.append(f"missing frozen migration: {relative_path}")
            continue
        current_blob = _git_blob(path)
        source_blob = _source_blob(source_commit, relative_path)
        if source_blob != expected_blob:
            failures.append(
                f"frozen source blob mismatch for {name}: lock={expected_blob} source={source_blob}"
            )
        if current_blob != expected_blob:
            failures.append(
                f"candidate drift for {name}: expected={expected_blob} current={current_blob}"
            )
        migration_payload.append(
            {
                "name": name,
                "git_blob_sha1": current_blob,
                "sha256": _sha256(path),
            }
        )

    aggregate_sha256 = _canonical_digest(migration_payload)
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "format_version": 1,
        "candidate_source_commit": source_commit,
        "candidate_source_tree": expected_source_tree,
        "current_head": current_head,
        "current_tree": current_tree,
        "migration_count": len(migration_payload),
        "migration_order": expected_names,
        "migrations": migration_payload,
        "migration_set_sha256": aggregate_sha256,
        "locked_tools": tool_payload,
        "lock_file_sha256": _sha256(LOCK_PATH),
        "failures": failures,
    }

    if args.output:
        output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if failures:
        print("V3 candidate freeze proof failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(
        "V3 candidate freeze proof passed: "
        f"{len(migration_payload)} migrations locked to {source_commit} "
        f"({aggregate_sha256})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
