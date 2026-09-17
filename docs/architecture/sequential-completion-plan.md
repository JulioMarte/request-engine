# Plan de implementación secuencial con sub-agentes

Fecha: 2026-09-16. Branch de referencia: `cohesion/system-optimization` (lane de
integración, PR #132). HEAD de referencia: `ba1acb0c`, revisión vigente `0055`.

Estado: **plan de ejecución propuesto, no certificación ni autorización de
despliegue**. Es el complemento operativo de
`architecture/auth-production-completion-plan.md` (que define el contenido de cada
bloque). Este documento define **cómo se ejecutan** los bloques restantes con
sub-agentes en una sola lane, sin paralelismo real.

Estado de bloques: B4, E1, E2, E3 y F-02 están completados con CI exact-head verde;
quedan pendientes F-01 y G/D6.

## 0. Restricciones duras (revisadas)

| Restricción | Evidencia | Consecuencia |
| --- | --- | --- |
| Una sola lane de integración | `tests/architecture/test_branch_workflow_contract.py` | Todo se commitea en `cohesion/system-optimization`; nada de PRs paralelos |
| Una sola cadena Alembic | `alembic heads` debe dar 1 | Una migración a la vez, en orden; `0001`–`0052` intactas |
| Una sola DB de test (`request_engine_current`) | `tests/e2e/conftest.py` | Una verificación DB/e2e a la vez |
| Recursos del host | Docker/CPU/RAM insuficientes | Sin worktrees ni contenedores de DB por bloque; reutilizar el PostgreSQL 18 existente |
| Certificación de publicación | `engineering-quality/local-publish-certification.md` | `certify_push` exact-SHA por integración; nunca `--no-verify` |

**Consecuencia de fondo:** el paralelismo se elimina. El ahorro viene de **aislar
contexto** con sub-agentes (recon, implementación, verificación, reparación)
ejecutados en serie, no de correr cosas a la vez.

## 1. Modelo de ejecución secuencial

```text
LANE ÚNICA: cohesion/system-optimization  (PR #132)
   │
   ├─ Bloque B4  ──► verificación ──► commit ──► certify ──► push ──► CI exact-head
   ├─ Bloque E1  ──► verificación ──► commit ──► certify ──► push ──► CI exact-head
   ├─ Bloque E2  ──► ...
   ├─ Bloque E3  ──► ...
   ├─ Bloque F-02 ─► ...
   ├─ Bloque F-01 ─► ...
   └─ Bloque G/D6 ─► ... (aceptación operacional, owner externo)
```

- Se trabaja directamente en la lane con commits coherentes (checkpoints).
  `git reset`/`revert` local si un bloque sale mal.
- `tmp/*` solo si un bloque necesita un experimento arriesgado; se descarta y
  nunca es head de PR.
- Cada bloque se cierra con CI exact-head verde antes de empezar el siguiente
  (evita apilar fallos).

## 2. Backlog ordenado (secuencial)

| # | Bloque | Depende de | Migración | Justificación del orden |
| --- | --- | --- | --- | --- |
| 1 | B4 auditoría append-only staff/agent/integration | — | 1 | Fundacional de auditabilidad; toca tenancy y sienta el patrón |
| 2 | E1 ceremonia upgrade controller-policy | B4 (patrón audit) | 1 | Habilita que roots existentes adquieran capabilities; habilita E2 |
| 3 | E2 onboarding identity-aware | E1, C-02 (hecho) | 0–1 | Consume hechos de E1 y C; puede requerir G para el blocker de operador |
| 4 | E3 `authority_inspect_resource` | E1 (registry) | 0–1 | Independiente de E2; cierra el contrato de diagnóstico |
| 5 | F-02 portabilidad IdP (test) | D2/D3 (hecho) | 0 | Barato y de bajo riesgo; puede adelantarse al puesto 1 |
| 6 | F-01 journey native-only fixture-free | B4+E1+E2+E3+C+D | 0 | Solo tiene sentido cuando el producto está completo |
| 7 | G/D6 aceptación operacional | decisiones D6 + todos | 0 | Requiere entorno real del owner; borradores pueden empezar antes |

Nota honesta: E2/E3 podrían intercambiarse; F-02 puede moverse al puesto 1 para un
cierre rápido sin tocar migraciones.

## 3. Bucle por bloque (uso de sub-agentes en serie)

```text
1. RECON/DESIGN   (sub-agente, contexto fresco, solo lectura)
      -> packet: archivos, capabilities, migración, garantías, tests, riesgos, falsabilidad
2. ORQUESTADOR    revisa el packet, congela contrato, redacta el prompt de implementación
3. IMPLEMENTACIÓN (sub-agente, contexto fresco + packet completo)
      -> código + tests en la lane (sin tocar 0001-0052)
4. VERIFICACIÓN   (orquestador + sub-agente verificador independiente)
      -> corre suites, inspecciona diff, mutation check, audita honestidad del reporte
5. REPARACIÓN     (sub-agente nuevo, si hay defectos) con hallazgos exactos -> volver a 4
6. CIERRE         commit coherente -> certify exact-SHA -> push -> CI exact-head
7. DOCS           actualizar status doc + current-guarantees.toml + proof-map; congelar bloque
```

Reglas:

- Un sub-agente por rol y por vez; nunca dos editando los mismos archivos.
- El verificador no es el implementador (independencia real).
- El orquestador nunca acepta un "pasó" sin comando + entorno + artefacto.

## 4. Paquete de contexto por sub-agente (plantilla)

```text
ROL: <recon|implementación|verificación|reparación> del bloque <ID>.
RAMA: cohesion/system-optimization. No crear PR, no tocar .github/development-integration-lane.
ESTADO: HEAD <sha>, migración vigente <rev>, DB request_engine_current en <rev>, árbol <limpio/dirty>.
LECTURAS OBLIGATORIAS: AGENTS.md raíz; src/**/AGENTS.md; docs/architecture/system-optimization-mode.md;
  docs/README.md; docs/10-module-ownership-map.md; README del módulo dueño; contrato del dominio;
  docs/testing/current-guarantees.toml; docs/testing/current-proof-map.toml; docs/07..09,13,14,15,16;
  auth-production-completion-plan.md (sección <ID>); auth-implementation-status.md.
CONTEXTO DEL BLOQUE: qué existe ya, qué NO cambia, migración permitida (una, append 0002+), capabilities.
CONTRATO DE EVIDENCIA: prueba falsable, PostgreSQL 18 real, sin seedear el resultado, mutation check si es invariante.
CONTRATO DE HONESTIDAD: reporta solo lo que corrió (comando+entorno+resultado); distingue
  implementado/validado/bloqueado/no hecho; expón decisiones, preexistentes y límites; prohibido maquillar.
DELEGACIÓN: puedes spawnear sub-agentes de recon/test de solo lectura; nunca en paralelo sobre los mismos archivos.
VERIFICACIÓN OBLIGATORIA: <comandos exactos del bloque> + `uv run python scripts/ci/ci_jobs.py python-quality`.
REPORTE: archivos; contrato; comandos+resultados; mutation red/green; qué NO se hizo; bloqueos.
```

## 5. Definición de terminado por bloque

Cada bloque cierra solo si:

1. contrato/capability/operationId documentados y coherentes con docs 15/16;
2. migración (si aplica) aplicada en `request_engine_current`, `0001`–`0052`
   intactas, `alembic heads` = 1;
3. pruebas falsables (DB/HTTP/e2e según el bloque) verdes, con mutation check en
   invariantes y carreras;
4. `python-quality` 12/12;
5. `certify_push` exact-SHA PASS y CI exact-head verde;
6. status doc + garantías + proof-map actualizados;
7. reporte honesto con lo que NO se cambió.

## 6. Protocolo de integración (serial)

1. Un bloque termina y pasa CI exact-head antes del siguiente.
2. Si `origin/development` se mueve, reconciliar la lane y reclamarla antes de
   continuar.
3. Nunca `--no-verify`, nunca lane mismatch, nunca PR desde `tmp/*`.
4. Merge a `development` solo con autorización explícita y exact-head verde
   (PR #132).

## 7. Riesgos (secuenciales)

| Riesgo | Mitigación |
| --- | --- |
| Apilar bloques rojos | No empezar el siguiente hasta CI exact-head verde del anterior |
| Deriva de la lane | Reconciliar con `origin/development` al inicio de cada bloque |
| Migración mal ordenada | Una sola `down_revision` = HEAD vigente; verificar `alembic heads` |
| Sub-agente que sobreafirma | Verificador independiente + comando/entorno/artefacto obligatorio |
| Contención del contenedor DB | Una suite a la vez; reutilizar el mismo contenedor; no recrear |
| Context rot entre bloques | Packet de contexto + handoff escrito al cerrar cada bloque |

## 8. Contrato de honestidad (idéntico en todos los prompts)

```text
- Declara branch, HEAD, dirty, migración aplicada y DB real usada.
- No reportes un check como pasado si no corrió contra el entorno previsto.
- Distingue implementado / validado / bloqueado / no hecho.
- Expón decisiones y preexistentes; no los ocultes tras un verde.
- Si no puedes probar algo, dilo y explica por qué.
- Pide a tus sub-agentes el mismo estándar.
```
