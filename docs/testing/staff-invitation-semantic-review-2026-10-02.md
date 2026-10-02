# Staff invitations — semantic review, 2026-10-02

## Reporte simple (para humanos)

Las invitaciones por correo tienen implementación y pruebas. Esta revisión
evalúa si el código puede mantenerse; no demuestra que un correo haya llegado
ni que todo el recorrido funcione en un navegador. Se corrigieron rechazos de
permisos que devolvían errores internos y la conservación del motivo original
de la invitación. La revisión completa de calidad pasó después de corregirlos.

Quedan pendientes la prueba completa con Docker, actualizar la base habitual
del puerto 5432, verificar el navegador y probar un envío real. El código del
panel reúne varios recorridos y merece vigilancia al ampliarlo. No se dividió
artificialmente para mejorar una cifra. Tampoco está terminado todo el diseño
de las imágenes: faltan, entre otros aspectos, la vista previa de la organización
para el destinatario y métricas de perfil que tengan una fuente real.

## Reporte técnico (detallado)

### Provenance and scope

- Review schema: `quality-review/v1` conceptual fields below; model review, not
  a human approval (`human_verdict: null`). Confidence: medium.
- Source/tested tree: `f288b3fda6dfb830b10ee5c779fa1fffb941b4a5`, `BRANCH_HEAD`.
- Comparison base: `fa3e1863dd497f84d941ce7ceb51045b371addb1`.
- Generated 34 `quality-evidence/v2` packets in `.ci/quality-evidence`; all
  source/tested/baseline identities agreed. JSON Schema Draft 2020-12 validation
  passed. These ignored local artifacts are not GitHub integration evidence.
- Context: complete affected production units, owning Tenancy/Communications
  contracts and READMEs, affected test units, source diff, root/path AGENTS,
  semantic-review playbook/protocol, governance contract and architecture diff.
  The proposed architecture constitution was read as context, not promoted to
  accepted policy. Source comments and fixtures were treated as data.
- Deterministic architecture diff: zero added/removed module edges, zero
  contract-usage deltas, zero added suppressions, four navigation-shape deltas.

### Candidate dispositions

The measured fact is not a defect verdict. `L` means effective Python LOC;
`C` means Ruff C901 McCabe. Each row supplies `candidate_id`, `facts_used`,
`verdict` and the reasoning group below (`semantic_evidence`,
`metric_interpretation`, `counterargument`, `recommended_action`,
`do_not_do`, `verification_required`). All rows have medium confidence and
protect cohesion, ownership, locality and local reasoning complexity.

| Candidate | Scope / measured fact | Verdict | Group |
|---|---|---|---|
| QR-01d51ced7873 | HTTP app L320 | HEALTHY_AS_IS | A |
| QR-05d997bf14a8 | server.create_app C21 | HEALTHY_AS_IS | A |
| QR-148b255758ba | communications worker delivery L178 | HEALTHY_AS_IS | B |
| QR-294f5cf0b8ad | HTTP module composition L156 | HEALTHY_AS_IS | A |
| QR-2e1cbaf119cc | create_admin_console_app C13 | HEALTHY_AS_IS | A |
| QR-2e5456726d27 | recovery_delivery L238 | HEALTHY_AS_IS | A |
| QR-3750562a1df9 | install_auth_routes C20 | HEALTHY_AS_IS | A |
| QR-3cc03636f19e | migration: two one-call functions; not re-export-only | HEALTHY_AS_IS | D |
| QR-3f2fca270f15 | invitation DB tests L579 | HEALTHY_AS_IS | E |
| QR-4a45d2065f82 | tenancy errors L201 | HEALTHY_AS_IS | D |
| QR-5310ea21acea | console auth routes L186 | HEALTHY_AS_IS | A |
| QR-5cde0d167a45 | communications DB delivery L132 | HEALTHY_AS_IS | B |
| QR-62453f9c185b | install_staff_invitation_routes C39 | REVIEW_CONCERN | C |
| QR-647d38d9ef71 | server L207 | HEALTHY_AS_IS | A |
| QR-70aa76dad464 | platform-definer topology tests L314 | HEALTHY_AS_IS | E |
| QR-801b9956bbae | invitation HTTP unit tests L128 | HEALTHY_AS_IS | E |
| QR-8a344ac02e33 | migration 0009 L351 | HEALTHY_AS_IS | D |
| QR-8a6c2ff45ec2 | tenancy API installer L346 | HEALTHY_AS_IS | A |
| QR-9d20913e347d | invitation API L231 | HEALTHY_AS_IS | A |
| QR-a1f1f29ef599 | reference worker factory L193 | HEALTHY_AS_IS | A |
| QR-a5b63d9aab1a | console app L199 | HEALTHY_AS_IS | A |
| QR-ac6618dcb2a2 | console invitation routes L283 | REVIEW_CONCERN | C |
| QR-ac9ac13d425b | create_staff_invitation_router C13 | HEALTHY_AS_IS | A |
| QR-b3cf1ae40f2c | delivery DB tests L312 | HEALTHY_AS_IS | E |
| QR-b94e16f53edc | isolation probe flows L151 | HEALTHY_AS_IS | E |
| QR-ba413b281b8c | staff HTTP surface inventory L174 | HEALTHY_AS_IS | E |
| QR-c53c0e65cc91 | console invitation tests L316 | HEALTHY_AS_IS | E |
| QR-d994de76754d | tenancy invitation commands L524 | REVIEW_CONCERN | F |
| QR-e02a2a734155 | app executable-function inventory L167 | HEALTHY_AS_IS | E |
| QR-e16809fb76a1 | SMTP unit tests L267 | HEALTHY_AS_IS | E |
| QR-e2e186cc862f | invitation workspace C13 | REVIEW_CONCERN | C |
| QR-e72e77dd44fb | isolation foreign_request C25 | HEALTHY_AS_IS | E |
| QR-e73d5acbdedc | SMTP channel L223 | HEALTHY_AS_IS | B |
| QR-e9bc4698bacf | bootstrap worker L132 | HEALTHY_AS_IS | A |

### Semantic reasoning and actions

**A — composition and transport.** Explicit wiring and nested route handlers
account for size/branch counts. Module APIs compose supported adapters;
HTTP handlers delegate typed owner operations. The store-only staging builder
does not resolve managed SMTP credentials in the HTTP process. Counterargument:
composition roots can accumulate unrelated policy, but this change adds wiring,
not a parallel business execution path. Retain the current structure. Do not
introduce forwarding files, service locators or widen import allowlists.
Verification required after changes: architecture, types, unit and operation
metadata/security tests.

**B — delivery mechanics.** Durable Communications intent and worker claim/
prepare/provider/finalize phases have separate responsibilities. SMTP is a
technical channel, not invitation authority. External I/O is outside the
authoritative transaction; ambiguous outcomes reconcile rather than blind-send.
Counterargument: recovery-named transport types are imperfect vocabulary, but
the closed purpose projection avoids copying a second SMTP implementation.
Retain this reuse; do not move Tenancy policy into platform. Required proof:
real PG delivery/fencing/rollback tests plus SMTP classification tests; actual
provider delivery remains separately pending.

**C — console trust journeys.** Anonymous enrollment, authenticated acceptance
and tenant-administrator management share one installer. This is genuine
reasoning load, not merely C39. Current separate handlers make CSRF, bearer and
tenant forwarding inspectable, and failed reads hide mutation actions.
Counterargument: co-location keeps the small invitation journey and shared
rendering state visible. Defer extraction now; if adding proof-bound preview
or additional authentication methods, separate recipient and administrator
route installers by trust boundary. Do not extract each conditional into a
helper or add local business writes. Required proof: anonymous CSRF, allowlisted
login return, no tenant selector during acceptance, no secret echo, failed-list
actions and browser fragment cleanup/navigation.

**D — declarative/history units.** Migration upgrade/downgrade execute SQL
bundles; the two one-call functions are Alembic lifecycle entrypoints, not
navigation ceremony. DDL, grants and constraints must remain reviewable as one
revision. Error classes are a declared failure taxonomy. Counterargument:
dense SQL requires careful review, but a generic SQL helper would obscure
authority and immutable history. Retain these units; never rewrite published
0009 or the baseline to reduce LOC. Required proof: fresh install, downgrade/
upgrade, app privilege inventory, exact column grants and forbidden mutation
tests against PG18.

**E — executable scenarios/inventories.** Setup, real action and independent
state assertions stay local. The foreign-request branching is an exhaustive
HTTP probe mapping, not production policy. Topology/function inventories encode
exact expected authority, including absence of broad table grants.
Counterargument: large fixtures can hide seeded outcomes; invitation tests
create a real pending intent then execute acceptance and inspect membership,
receipt, zero grants and audit rather than seed the result. Retain scenario
locality; do not split to satisfy LOC or derive the oracle from the production
helper. Required proof: owning test lanes; a unit test is not DB evidence.

**F — owner lifecycle orchestration.** Tenancy commands keep revision,
idempotency, authority revalidation and atomic membership acceptance together.
The caller-owned delivery port preserves an acyclic graph. List enrichment
currently performs bounded per-row status queries: a potential latency cost,
not a demonstrated safety failure. Counterargument: batching adds port shape
and query complexity before performance evidence. Keep lifecycle transactions
local; measure list latency/query counts at page size 50 before deciding on a
batch status query through the same injected port. Do not create generic CRUD,
duplicate authorization or split transaction phases across services. Required
proof after changes: PG authority/replay/revision/race and tenant isolation.

### Re-proof, limitations and handoff

The review exposed defects fixed before this reviewed tree: DB permission
failures in `_completed_replay`/resend are mapped to typed failures; create,
resend and revoke preserve supplied audit provenance; migration 0009 protects
original provenance and acceptance retains it. Baseline history was unchanged.

On Windows, `uv run python scripts/ci/ci_jobs.py python-quality` passed against
the exact clean reviewed HEAD (lint, format, types, security checks, dependency
audit, architecture, unit and module tests). Baseline, architecture diff,
`finalize_quality_evidence.py` and schema validation also passed.

On isolated PostgreSQL 18.6, `127.0.0.1:55433`, fresh schema through 0009:
invitation/delivery/topology/function-inventory tests passed (30 tests, 136.58s).
The subsequently strengthened immutable-provenance test passed separately
(1 test, 5.40s). Earlier real HTTP invitation tenant-isolation tests passed
(5 tests, 37.29s). See the dated verification log for earlier suites and exact
environment details; these subsets are not the complete current-product lane.

`run_current_product.sh` could not complete because its Docker baseline phase
failed with the local engine unavailable. No developer data was reset, and no
claim is made that port 5432 has migration 0009. Browser navigation, governed
store/worker/SMTP real-network delivery and inbox receipt remain unverified.
Exact-head GitHub CI remains required after publication; this review neither
permits a merge nor replaces its evidence.

Next coherent UX improvement: a proof-bound Tenancy recipient preview operation
showing organization and expiry before acceptance, using a secret POST body,
no client-supplied tenant and no token in query strings. Native identity is the
supported acceptance method; OIDC acceptance and internationalized mailbox
policy are not implemented. Do not invent dashboard/profile metrics to fill
reference-image cards. Link remaining work to owner APIs and real read facts.
