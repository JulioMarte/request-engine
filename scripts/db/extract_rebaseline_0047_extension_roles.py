"""Extract the audited extension-role ensure blocks verbatim from the old chain."""

import re
import runpy
import sys
import textwrap
from pathlib import Path

W = Path(sys.argv[1])
V = W / "migrations" / "versions"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else W


def first_do_block(name: str) -> str:
    text = (V / name).read_text(encoding="utf-8")
    start = text.index("DO $$")
    end = text.index("END $$;", start) + len("END $$;")
    # include indentation-normalized block
    line_start = text.rfind("\n", 0, start) + 1
    block = text[line_start:end]
    return textwrap.dedent(block)


WEBAUTHN_FULL = first_do_block("0037_native_webauthn_challenge_retention.py")
_FK = WEBAUTHN_FULL.index("    IF EXISTS (\n        SELECT 1 FROM pg_constraint")
WEBAUTHN_PRE = WEBAUTHN_FULL[:_FK].rstrip() + "\n    -- The dependent-foreign-key check needs request_engine.webauthn_challenges;\n    -- that historical 0037 check runs after the schema payload.\nEND $$;"

recorder = """DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_engine_retention_recorder') THEN
        RAISE EXCEPTION 'legacy retention recorder group exists; reset clusters that predate the 0047 rebaseline'
            USING ERRCODE='55000';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_retention_recorder') THEN
        CREATE ROLE request_retention_recorder NOLOGIN NOSUPERUSER
            NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;"""

sections = [
    (
        "request_retention_recorder (historical 0013 creation under the 0020 canonical name; "
        "its complete 0020 inventory audit runs after the schema payload)",
        recorder,
    ),
    ("request_proof_cleanup_worker (historical 0024)", first_do_block("0024_temporary_proof_cleanup.py")),
    (
        "request_webauthn_retention / request_webauthn_retention_definer (historical 0037)",
        WEBAUTHN_PRE,
    ),
    ("request_http_admission_definer (historical 0038)", first_do_block("0038_shared_http_auth_admission.py")),
    (
        "request_operator_metrics / request_operator_metrics_definer (historical 0039)",
        first_do_block("0039_operator_metrics_projection.py"),
    ),
]

out = [
    "-- Audited Request Engine extension-role ensure blocks.",
    "-- Extracted verbatim from the collapsed 0013/0020/0024/0037/0038/0039 revisions.",
    "-- Each block creates its closed-namespace NOLOGIN group only when missing and",
    "-- fails closed when an existing cluster-global role is unsafe. Credentials are",
    "-- intentionally forbidden from this payload.",
    "",
    "SELECT pg_advisory_xact_lock(731527893422021);",
    "",
]
for title, block in sections:
    out.append(f"-- {title}")
    out.append(block.strip("\n"))
    out.append("")
(OUT / "migrations" / "baseline" / "0001_extension_roles.sql").write_text(
    "\n".join(out), encoding="utf-8", newline="\n"
)

audit = runpy.run_path(str(V / "0020_retention_recorder_role_contract.py"))["ROLE_INVENTORY_SQL"]
(OUT / "migrations" / "baseline" / "0001_post_install_audit.sql").write_text(
    "-- Post-install retention-recorder inventory audit (historical 0020 ROLE_INVENTORY_SQL).\n"
    "-- Runs after the schema payload because it pins the recorder's exact ACL contract.\n"
    + audit.strip("\n")
    + "\n\n-- Historical 0037 dependent-foreign-key check (needs the installed table).\n"
    + "DO $$ BEGIN\n"
    + WEBAUTHN_FULL[_FK:].strip("\n")
    + "\n",
    encoding="utf-8",
    newline="\n",
)
print("ok")
