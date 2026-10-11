"""The migration convergence oracle rejects broad or missing receipt privileges."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROWS = [
    ("actor_principal_id", "SELECT", "NO"),
    ("idempotency_key_digest", "SELECT", "NO"),
    ("intent_digest", "SELECT", "NO"),
    ("native_identity_id", "SELECT", "NO"),
    ("login_handle", "SELECT", "NO"),
    ("actor_principal_id", "INSERT", "NO"),
    ("idempotency_key_digest", "INSERT", "NO"),
    ("intent_digest", "INSERT", "NO"),
    ("native_identity_id", "INSERT", "NO"),
    ("login_handle", "INSERT", "NO"),
    ("correlation_id", "INSERT", "NO"),
]


@pytest.mark.parametrize(
    "columns,table_acl,denied",
    [
        (ROWS, [], False),
        (ROWS + [("correlation_id", "SELECT", "NO")], [], True),
        (ROWS + [("created_at", "INSERT", "NO")], [], True),
        (ROWS[1:], [], True),
        ([("actor_principal_id", "SELECT", "YES"), *ROWS[1:]], [], True),
        (ROWS, [("SELECT",)], True),
    ],
)
def test_receipt_privilege_oracle_is_closed(
    columns: list[tuple[str, str, str]], table_acl: list[tuple[str]], denied: bool
) -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts/db/prove_multidatabase_migration_compatibility.py"
    )
    spec = importlib.util.spec_from_file_location("multidb_receipt_oracle", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = MagicMock()
    connection.execute.return_value.fetchall.side_effect = [columns, table_acl]
    if denied:
        with pytest.raises(RuntimeError, match="privilege convergence mismatch"):
            module._verify_native_receipt_privileges(connection)
    else:
        module._verify_native_receipt_privileges(connection)


@pytest.mark.parametrize("extra", [None, "table", "column", "database", "type", "default"])
def test_cleanup_worker_oracle_rejects_every_extra_acl_class(extra: str | None) -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts/db/prove_multidatabase_migration_compatibility.py"
    )
    spec = importlib.util.spec_from_file_location("multidb_cleanup_oracle", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (
        False,
        False,
        False,
        False,
        False,
        False,
        None,
    )
    rows = [
        ("function", "claim_temporary_proof_cleanup", "EXECUTE", False),
        ("function", "finish_temporary_proof_cleanup", "EXECUTE", False),
        ("schema", "request_cmd", "USAGE", False),
    ]
    if extra is not None:
        rows.append((extra, "unreviewed_object", "SELECT", False))
    connection.execute.return_value.fetchall.return_value = rows
    if extra is None:
        module._verify_cleanup_worker_privileges(connection)
    else:
        with pytest.raises(RuntimeError, match="cleanup worker ACL"):
            module._verify_cleanup_worker_privileges(connection)
