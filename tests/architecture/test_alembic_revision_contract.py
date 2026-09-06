import ast
from pathlib import Path

MIGRATIONS = Path("migrations/versions")
ALEMBIC_VERSION_NUM_MAX_LENGTH = 32


def _revision_id(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "revision":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError(f"{path} does not declare a literal revision id")


def test_alembic_revision_ids_fit_version_table_and_are_unique() -> None:
    revisions: dict[str, Path] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        revision = _revision_id(path)
        assert len(revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH, (
            f"{path}: revision {revision!r} is {len(revision)} characters; "
            f"alembic_version.version_num supports at most "
            f"{ALEMBIC_VERSION_NUM_MAX_LENGTH}"
        )
        assert revision not in revisions, (
            f"duplicate Alembic revision {revision!r}: {revisions[revision]} and {path}"
        )
        revisions[revision] = path
