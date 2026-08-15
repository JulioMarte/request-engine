#!/usr/bin/env python3
"""Audit Phase 6 tests for release-proof quality regressions."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
RELEASE_ROOTS: Final = (
    REPO_ROOT / "tests" / "db",
    REPO_ROOT / "tests" / "e2e",
    REPO_ROOT / "tests" / "integration" / "v3_first_vertical",
    REPO_ROOT / "tests" / "integration" / "v3_booking_core",
    REPO_ROOT / "tests" / "integration" / "v3_booking_commitments",
    REPO_ROOT / "tests" / "integration" / "v3_slot_offer_recovery",
    REPO_ROOT / "tests" / "integration" / "v3_reservation_lifecycle",
    REPO_ROOT / "tests" / "integration" / "v3_worker_runtime",
)
CONCURRENCY_NAME_TOKENS: Final = ("race", "concurrent", "soak", "crash", "reclaim")


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    line: int
    rule: str
    message: str


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return None


def _marker_name(node: ast.AST) -> str | None:
    name = _dotted_name(node)
    prefix = "pytest.mark."
    if name and name.startswith(prefix):
        return name.removeprefix(prefix).split(".", 1)[0]
    return None


def _module_markers(tree: ast.Module) -> set[str]:
    markers: set[str] = set()
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        has_pytestmark = any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in statement.targets
        )
        if not has_pytestmark:
            continue
        if isinstance(statement.value, ast.List | ast.Tuple):
            values = statement.value.elts
        else:
            values = [statement.value]
        for value in values:
            marker = _marker_name(value)
            if marker:
                markers.add(marker)
    return markers


def _test_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def _contains_assertion(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call) and _dotted_name(child.func) in {
            "pytest.raises",
            "pytest.fail",
        }:
            return True
    return False


def _required_markers(relative: str) -> tuple[str, ...]:
    if relative.startswith("tests/integration/v3_"):
        return ("integration", "postgres")
    if relative.startswith("tests/e2e/"):
        return ("e2e", "postgres")
    return ()


def _audit_test_function(
    relative: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    inherited_markers: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    markers = inherited_markers | {
        marker
        for decorator in node.decorator_list
        if (marker := _marker_name(decorator)) is not None
    }

    for required in _required_markers(relative):
        if required not in markers:
            findings.append(
                Finding(
                    "error",
                    relative,
                    node.lineno,
                    f"missing-{required}-marker",
                    f"{node.name} must carry the {required} release marker",
                )
            )

    lower_name = node.name.lower()
    is_concurrency_named = any(token in lower_name for token in CONCURRENCY_NAME_TOKENS)
    if is_concurrency_named and "concurrency" not in markers:
        findings.append(
            Finding(
                "error",
                relative,
                node.lineno,
                "missing-concurrency-marker",
                f"{node.name} describes a race/concurrency proof but lacks concurrency marker",
            )
        )

    if not _contains_assertion(node):
        findings.append(
            Finding(
                "warning",
                relative,
                node.lineno,
                "no-local-assertion",
                f"{node.name} has no local assert/pytest.raises; verify its delegated oracle",
            )
        )

    for child in ast.walk(node):
        is_bare_false = (
            isinstance(child, ast.Assert)
            and isinstance(child.test, ast.Constant)
            and child.test.value is False
        )
        if is_bare_false:
            findings.append(
                Finding(
                    "error",
                    relative,
                    child.lineno,
                    "bare-assert-false",
                    "Use an assertion with an observable state and diagnostic context",
                )
            )

        if not isinstance(child, ast.Call):
            continue

        call_name = _dotted_name(child.func)
        if call_name in {"pytest.skip", "pytest.xfail"}:
            findings.append(
                Finding(
                    "error",
                    relative,
                    child.lineno,
                    "runtime-skip-or-xfail",
                    "Release-proof tests must not silently skip or xfail at runtime",
                )
            )
        if call_name == "pytest.raises" and child.args:
            raised = _dotted_name(child.args[0])
            if raised in {"Exception", "BaseException"}:
                findings.append(
                    Finding(
                        "error",
                        relative,
                        child.lineno,
                        "broad-exception-oracle",
                        "Assert the exact exception class or database error contract",
                    )
                )
        if call_name in {"time.sleep", "asyncio.sleep"} and child.args:
            duration = child.args[0]
            if isinstance(duration, ast.Constant) and isinstance(duration.value, int | float):
                seconds = float(duration.value)
                severity = "error" if seconds > 2.0 else "warning"
                findings.append(
                    Finding(
                        severity,
                        relative,
                        child.lineno,
                        "wall-clock-synchronization",
                        (
                            f"{call_name}({seconds:g}) makes concurrency evidence timing-dependent; "
                            "prefer a DB barrier or lock observation"
                        ),
                    )
                )
        if call_name and call_name.endswith(".result"):
            has_timeout = any(keyword.arg == "timeout" for keyword in child.keywords)
            if not has_timeout:
                findings.append(
                    Finding(
                        "warning",
                        relative,
                        child.lineno,
                        "unbounded-future-wait",
                        "Future.result() needs a timeout so deadlocks become bounded failures",
                    )
                )

    for decorator in node.decorator_list:
        marker = _marker_name(decorator)
        if marker in {"skip", "skipif", "xfail"}:
            findings.append(
                Finding(
                    "error",
                    relative,
                    decorator.lineno,
                    "decorated-skip-or-xfail",
                    "Release-proof tests must not carry skip/skipif/xfail markers",
                )
            )

    return findings


def audit() -> dict[str, object]:
    findings: list[Finding] = []
    files = sorted({path for root in RELEASE_ROOTS for path in root.glob("test_*.py")})
    test_count = 0

    for path in files:
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        inherited_markers = _module_markers(tree)
        functions = _test_functions(tree)
        test_count += len(functions)

        names: dict[str, int] = {}
        for function in functions:
            if function.name in names:
                findings.append(
                    Finding(
                        "error",
                        relative,
                        function.lineno,
                        "duplicate-test-name",
                        (
                            f"{function.name} duplicates a test first declared on line "
                            f"{names[function.name]}"
                        ),
                    )
                )
            else:
                names[function.name] = function.lineno
            findings.extend(_audit_test_function(relative, function, inherited_markers))

    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    return {
        "status": "PASS" if not errors else "FAIL",
        "files_audited": len(files),
        "tests_audited": test_count,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [asdict(finding) for finding in errors],
        "warnings": [asdict(finding) for finding in warnings],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if result["status"] == "PASS":
        print(
            "V3 test quality audit passed: "
            f"{result['tests_audited']} tests, {result['warning_count']} non-blocking warnings."
        )
        return 0

    print(f"V3 test quality audit failed with {result['error_count']} blocking finding(s):")
    for finding in result["errors"]:
        print(
            f"- {finding['path']}:{finding['line']} [{finding['rule']}] {finding['message']}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
