import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/v3_scratch_database.py"
SPEC = importlib.util.spec_from_file_location("v3_scratch_database_isolation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_scratch_environment_cannot_inherit_outer_runtime_database_bindings() -> None:
    base_env = {
        "PGDATABASE": "outer_candidate",
        "PHASE6_HEAD_SHA": "a" * 40,
        "REQUEST_ENGINE_APP_DATABASE_URL": "postgresql+asyncpg://app@outer/candidate",
        "REQUEST_ENGINE_WORKER_DATABASE_URL": "postgresql+asyncpg://worker@outer/candidate",
        "REQUEST_ENGINE_ADMIN_DATABASE_URL": "postgresql+asyncpg://admin@outer/candidate",
        "REQUEST_ENGINE_APP_ROLE_NAME": "re_g19_app_outer",
        "REQUEST_ENGINE_WORKER_ROLE_NAME": "re_g19_worker_outer",
        "REQUEST_ENGINE_ADMIN_ROLE_NAME": "re_g19_admin_outer",
    }

    scratch = module._scratch_environment(base_env, "scratch_v3")

    assert scratch["PGDATABASE"] == "scratch_v3"
    assert scratch["PHASE6_HEAD_SHA"] == "a" * 40
    assert not (module.RUNTIME_DATABASE_ENV_KEYS & scratch.keys())
    assert base_env["REQUEST_ENGINE_APP_DATABASE_URL"].endswith("/candidate")
