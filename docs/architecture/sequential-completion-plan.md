# Plan de implementación secuencial con sub-agentes

> **Trust-root amendment (2026-09-18):** this plan remains useful for the
> already-running E2E/F-01/G work, but the next platform trust-root implementation
> sequence is P0-P7 in `instance-claim-platform-owner-plan.md`. In particular,
> F-01's current CLI bootstrap is transitional evidence and must eventually be
> replaced by the HTTP Instance-claim journey without changing the reusable E2E
> platform boundary.

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization` (lane de integración, PR #132).

Estado: **plan operativo de ejecución, no certificación ni autorización de despliegue**. Complementa `architecture/auth-production-completion-plan.md` y la plataforma E2E oficial definida en `architecture/docker-e2e-ci-plan.md`.

Estado de bloques: B4, E1, E2, E3 y F-02 están completados con evidencia previa; quedan F-01, la implementación de la plataforma E2E reusable y G/D6.

## 0. Restricciones duras

| Restricción | Consecuencia |
| --- | --- |
| Una sola lane de integración | Todo se integra en `cohesion/system-optimization`; sin PRs paralelos de implementación |
| Una sola cadena Alembic | Una migración a la vez; un solo current head |
| Exact-head evidence | Ningún bloque se declara cerrado por evidencia de un SHA anterior |
| Publicación disciplinada | Nunca `--no-verify`; merge sólo con autorización explícita |
| Falsificabilidad | Un verde sin oracle real no cuenta como prueba |

### Aclaración sobre bases de datos de test

Para el bucle local/DB tradicional se puede reutilizar una DB dedicada cuando la suite y los recursos del host lo justifiquen.

Para la **plataforma system/E2E reusable**, la regla es distinta:

```text
cada suite obtiene un mundo efímero limpio por defecto
```

`all` no significa ejecutar suites sobre una misma DB contaminada. Las imágenes/caches se reutilizan; el estado autoritativo no.

## 1. Modelo de ejecución

```text
LANE ÚNICA: cohesion/system-optimization
   │
   ├─ bloque de producto/arquitectura
   │      ↓
   │   narrow verification
   │      ↓
   │   commit / exact-head CI
   │
   ├─ plataforma E2E reusable
   │      ↓
   │   generic runner + suite registry + isolation + profiles
   │
   ├─ F-01
   │      ↓
   │   suite consumidora de la plataforma
   │
   └─ G/D6
          ↓
       aceptación operacional externa donde CI no basta
```

La plataforma E2E no es un bloque F-01 privado. Es infraestructura reusable para cualquier future system journey.

## 2. Backlog restante

| # | Bloque | Depende de | Resultado esperado |
| --- | --- | --- | --- |
| 1 | E2E platform P2b/P3a | Docker smoke existente | evidence hardening, generic runner, suite registry, edge/backend, profiles, isolation |
| 2 | E2E platform P3b | P3a | fresh-world orchestration, namespaced evidence, `suite=<name|all>` |
| 3 | F-01 | plataforma reusable + B4/E1/E2/E3/C/D | suite fixture-free native-only, black-box, fault injection |
| 4 | suites dirigidas adicionales | plataforma reusable | booking/authority/recovery/worker según valor/riesgo |
| 5 | OIDC / Authentik | plataforma reusable + D2/D3 | suite/profile opt-in Native→OIDC completa |
| 6 | G/D6 | todos + decisiones externas | aceptación operacional que no puede certificarse sólo en GitHub CI |

La prioridad inmediata es terminar la plataforma reusable antes de cablear F-01 a infraestructura específica.

## 3. Bucle por bloque

```text
1. RECON/DESIGN
      -> contratos, owners, riesgos, suites afectadas, falsabilidad
2. ORQUESTADOR
      -> congela alcance y Definition of Done
3. IMPLEMENTACIÓN
      -> código/tests/docs en la lane
4. VERIFICACIÓN INDEPENDIENTE
      -> narrow proof + owning CI lane + adversarial inspection
5. REPARACIÓN
      -> hallazgos concretos; volver a 4
6. CIERRE
      -> commit coherente + exact-head CI
7. DOCS
      -> status/guarantees/proof map/plataforma E2E cuando aplique
```

Reglas:

- un agente implementador a la vez sobre archivos mutables compartidos;
- el verificador no acepta “pasó” sin comando, entorno y artifact;
- los system/E2E nuevos deben declarar qué suite reusable los posee;
- no crear Compose/workflow duplicado si el suite registry + profiles resuelven el caso.

## 4. Contrato para nuevas suites E2E

Toda suite system/E2E debe declarar:

```text
name
risk/guarantee
selector
required services/profiles
fresh-world policy
fault-injection requirements
expected artifacts
PR/merge/nightly/manual eligibility
```

Una suite normal debe poder añadirse sin:

```text
nuevo compose completo
nuevo workflow copiado
nuevo runner image sólo por convenience
acceso PostgreSQL desde el black-box runner
```

Excepciones se documentan en `docker-e2e-ci-plan.md`.

## 5. Paquete de contexto por sub-agente

```text
ROL: <recon|implementación|verificación|reparación> del bloque <ID>.
RAMA: cohesion/system-optimization.
ESTADO: HEAD <sha>, Alembic head, árbol <clean/dirty>.
LECTURAS: docs/README.md; owner contract; docs 07/09/13/14/15/16;
  auth-production-completion-plan.md; auth-implementation-status.md;
  docker-e2e-ci-plan.md cuando el trabajo toque system/E2E/CI.
CONTRATO DE EVIDENCIA: prueba falsable; boundary real; no seedear outcome.
CONTRATO DE HONESTIDAD: implementado/validado/bloqueado/no hecho claramente separados.
VERIFICACIÓN: comandos exactos + owning CI lane.
REPORTE: archivos, contrato, resultados, failure semantics, qué NO se hizo.
```

## 6. Definition of Done por bloque

Un bloque cierra sólo si:

1. contrato/owner/capability/operationId coherentes cuando aplique;
2. migración correcta y único Alembic head cuando aplique;
3. prueba falsable en el boundary adecuado;
4. ausencia de side effects importantes verificada;
5. quality/architecture lane correspondiente verde;
6. exact-head CI verde para el alcance requerido;
7. status/docs/guarantees/proof map actualizados;
8. si crea system/E2E, la suite está registrada en la plataforma reusable y produce evidence namespaceado;
9. reporte declara qué no fue probado.

## 7. Protocolo de integración

1. No apilar bloques rojos deliberadamente.
2. Si `development` cambia, reconciliar antes de cerrar el bloque.
3. Nunca `--no-verify` para forzar publicación.
4. Merge sólo con autorización explícita y exact-head evidence.
5. Checks E2E caros pueden permanecer experimentales hasta calibrar costo/flakiness, según la policy de la plataforma.

## 8. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Infra E2E acoplada a F-01 | generic runner + suite registry |
| Tests order-dependent | fresh world por suite |
| Coste excesivo | profiles + selección de suites por riesgo + `all` manual/nightly |
| Falso aislamiento | isolation proof automatizado |
| Duplicación de CI | reusable workflow/orchestrator parametrizado |
| Falso verde | oracle independiente + negative side-effect assertions |
| Sobreafirmación | exact-head artifacts + verificación independiente |
| Secrets en evidence | sanitización estructural + secret workspace fuera de artifacts |

## 9. Contrato de honestidad

```text
- Declara branch/HEAD exactos.
- No reportes un check como pasado si no corrió contra el entorno previsto.
- Distingue implementado / validado / bloqueado / no hecho.
- Un smoke verde no implica que la plataforma reusable esté terminada.
- Una suite verde no certifica properties fuera de su scope.
- Si CI no puede probar algo production-shaped, se registra como G/D6, no se simula como certificado.
```
