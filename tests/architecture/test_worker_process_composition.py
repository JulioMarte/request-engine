import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "src/request_engine/entrypoints/worker/app.py"
BOOTSTRAP = REPO_ROOT / "src/request_engine/bootstrap/worker.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_worker_entrypoint_remains_independent_of_business_adapters() -> None:
    imports = _imports(ENTRYPOINT)
    assert not {
        name
        for name in imports
        if name.startswith("request_engine.modules.") and ".adapters." in name
    }


def test_bootstrap_exposes_split_worker_and_domain_factories() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    assert "worker_session_factory: SessionFactory" in source
    assert "domain_session_factory: SessionFactory" in source
    assert "PostgresScheduledActionWorker(worker_session_factory)" in source
    assert "PostgresOutboxWorker(worker_session_factory)" in source
    assert "PostgresProviderEventWorker(worker_session_factory)" in source
    assert "PostgresReminderOccurrenceCommands(domain_session_factory)" in source
    assert "no_show_factory(domain_session_factory)" in source
    assert "slot_offer_expiry_factory(domain_session_factory)" in source
    assert "worker_session_factory is domain_session_factory" in source


def test_worker_console_script_points_to_deployment_entrypoint() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["request-engine-worker"] == (
        "request_engine.entrypoints.worker.cli:main"
    )
