# Admin dashboard validation checkpoint — 2026-10-11

Scope: `feature/admin-dashboard-completion`, based on the merged PR #137 at
`cb211a56e8948f0872952884927f49c2efb45e93`. This checkpoint records executed local
proof, not production installation acceptance. Final published-commit CI status
belongs to the pull request and its Actions runs.

## Executed proof

| Boundary | Command / environment | Observed result |
| --- | --- | --- |
| Console routes, templates and browser scripts | `uv run pytest tests/unit/admin_console tests/architecture/test_admin_tenant_configuration_projection.py -q`, Python 3.13.16, controlled upstream | 410 passed before the final readiness/search regressions |
| Final tenant task projection | `uv run pytest tests/unit/admin_console/test_tenant_configuration.py tests/architecture/test_admin_tenant_configuration_projection.py -q` | 50 passed; 99 mounted curated operations and explicit remaining operator destinations |
| Inventory and HTTP classification | Fresh PostgreSQL 18.6, migrated through 0040, restricted application role, Catalog/Queue read tests plus public HTTP surface contract | 10 passed, including current-grant revocation, Party scope, tenant opacity and bounded pagination |
| Policy and populated upgrade | Fresh PostgreSQL 18.6, initial-policy tests and `test_tenant_controller_v7_populated_upgrade.py` | 20 passed, including v3/v6 provisioning replay and physical 0039 → head preserving pending v6 consent |
| Governed adoption | PostgreSQL 18.6, `test_controller_policy_adoption_http.py` legacy-policy journey | Six source policies passed; v6 adds exactly `queue.read_configuration` |
| Independent migration review | Separate PostgreSQL 18.6 run and installed function catalog comparison before/after 0040 | 26 selected tests passed; function owner, ACL, SECURITY DEFINER and search_path unchanged |
| Browser interaction | Tracked optional `tests/browser/admin_console/run.sh`; Chromium 141.0.7390.37; real console with simulated upstream | Desktop/mobile 320 px, focus/Escape, no-JS navigation, confirmation, private-fetch secret clearing and reload without POST replay passed |
| Full local current-product runner | `bash scripts/ci/run_current_product.sh` in an isolated native PostgreSQL 18.6 cluster | Migration and schema export ran; runner stopped at baseline proof because Docker is unavailable. This is not a passed full lane |

The canonical Python-quality job and complete Docker/PostgreSQL remote CI must
be checked on the published candidate. Local component/DB results do not replace
that evidence. Semantic review records carry explicit scope and source hashes;
no model verdict is represented as human approval.

## Remaining product and operational limits

- Current administrative API coverage is not a claim of a bespoke visual editor
  for every complex schema or a new daily-service execution client.
- Owner reads do not expose every policy's current revision. Those forms require
  an identifier/revision from an existing authorized owner response; the console
  never invents it. Inventory links open prefilled read forms for explicit execution.
- Navigation works without JavaScript; private invitation redemption and code
  issuance stay disabled until the fetch handler is installed.
- Browser proof has a simulated upstream and does not prove a live WebAuthn
  ceremony. PostgreSQL proofs have restricted real DB boundaries but are not
  container installation proof.
- Production mail acceptance, external backup durability, host/network security,
  human alert receipt and operational acceptance remain separate work.
