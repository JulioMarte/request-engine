from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"


class SecurityVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[str] = []

    def _report(self, node: ast.AST, rule: str) -> None:
        line = getattr(node, "lineno", 0)
        self.findings.append(f"{self.path.relative_to(ROOT)}:{line}: {rule}")

    def visit_Call(self, node: ast.Call) -> None:
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr

        if name in {"eval", "exec"}:
            self._report(node, f"dynamic-code-execution:{name}")

        if name in {"run", "Popen", "call", "check_call", "check_output"}:
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    self._report(node, "subprocess-shell-true")

        if name in {"loads", "load"} and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "pickle":
                self._report(node, "unsafe-pickle-deserialization")

        self.generic_visit(node)


def main() -> int:
    findings: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = SecurityVisitor(path)
        visitor.visit(tree)
        findings.extend(visitor.findings)

    if findings:
        print("Python security findings:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("No forbidden dynamic execution, shell=True, or pickle loads found in src/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
