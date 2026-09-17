# Plataforma reusable de E2E real en Docker para GitHub CI

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization`.

Estado: **arquitectura oficial de system/E2E; core reusable P3a/P3b implementado y validado en CI para el lane black-box base.** F-01, fault injection completo, worker real y policy final de coste/gating siguen pendientes. No es certificación ni autorización de despliegue a producción.

Este documento define la **plataforma reusable de CI E2E de Request Engine**. F-01 es una suite consumidora de esta plataforma, igual que suites presentes o futuras de surface contract, booking, authority, recovery, worker, OIDC u otras capacidades cross-module.

El principio rector es:

> **El deployment bajo prueba es estable y reusable; el workload de prueba es intercambiable.**

`architecture/auth-production-completion-plan.md` sigue siendo la fuente normativa del contenido de F-01. Este documento define cómo ejecutar F-01 —y otros journeys— de forma aislada, reproducible, black-box y falsificable.

## 0. Decisión arquitectónica oficial

La plataforma se divide en dos planos:

```text
                         GitHub Actions
                              │
                       E2E orchestrator
                              │
               ┌──────────────┴──────────────┐
               │                             │
        Deployment Engine               Test Engine
               │                             │
               │                     suite registry
               │                             │
               ▼                             ▼
     request-engine:<git-sha>          e2e-runner:<git-sha>
     PostgreSQL 18                     ├── smoke
     API                               ├── surface-contract
     control-plane                     ├── booking [future]
     worker [profile]                  ├── recovery [future]
     Vault [profile]                   ├── f01 [future]
     Mailpit [profile]                 └── ...
     [Authentik future]
```

`all` no es una suite interna del runner. Es una operación del **orquestador de plataforma** que enumera las suites habilitadas y ejecuta cada una en un mundo fresco.

La infraestructura no se duplica por suite. Existe una definición de deployment E2E de referencia y una definición separada del workload.

No queremos:

```text
compose.f01.yaml
compose.booking.yaml
compose.recovery.yaml
compose.worker.yaml
```

Queremos:

```text
deploy/reference/compose.e2e.yaml
        ×
tests/system_e2e/suites.toml
        ×
e2e-runner intercambiable
```

Las excepciones requieren una diferencia real de topología o toolchain, no comodidad del test.

## 1. Unidad reusable y clean install

La unidad reusable es el stack instalado desde cero:

```text
PostgreSQL 18
    ↓
migrations
    ↓
runtime database identities
    ↓
bootstrap trust root
    ↓
API + control-plane
    ↓
worker/providers opcionales según suite
```

La misma instalación contractualmente reproducible puede recibir diferentes suites black-box.

Invocaciones canónicas actuales:

```bash
bash scripts/ci/run_e2e_platform.sh smoke
bash scripts/ci/run_e2e_platform.sh surface-contract
bash scripts/ci/run_e2e_platform.sh all
```

Una suite nueva ordinaria no debe requerir copiar Compose ni crear un workflow específico.

## 2. Separación de responsabilidades

### 2.1 GitHub Actions / outer orchestrator

GitHub Actions orquesta infraestructura; no contiene reglas de negocio del journey.

Responsabilidades:

- checkout;
- invocar el orquestador repository-local;
- propagar el selector de suite;
- conservar artifacts aun en failure;
- publicar summary;
- permitir ejecución manual y reutilización desde otros workflows.

`.github/workflows/docker-e2e.yml` ya expone:

- `pull_request` → `smoke` por defecto durante calibración;
- `workflow_dispatch` con input `suite`;
- `workflow_call` con input `suite`.

El workflow no debe convertirse en una matriz de `if suite == ...` con lógica de negocio.

### 2.2 Imagen única de Request Engine

Se mantiene **build once**:

```text
request-engine:<git-sha>
        ├── migrate
        ├── platform bootstrap CLI
        ├── API
        ├── control-plane
        └── worker
```

Son procesos/contenedores distintos cuando sus ciclos de vida lo requieren, pero salen del mismo artefacto inmutable. PostgreSQL permanece separado.

CI comprueba identidad efectiva de imagen para las superficies Request Engine relevantes, no sólo tags nominales.

### 2.3 Imagen genérica `e2e-runner`

La imagen actual se construye desde `deploy/reference/e2e-runner.Dockerfile` y copia únicamente el runner black-box de `tests/system_e2e/runner.py`.

Actualmente es intencionalmente mínima y usa la stdlib de Python para HTTP/JSON. No instala Request Engine, `psycopg`, SQLAlchemy, Docker CLI ni dependencias de aplicación. Si suites futuras justifican pytest/httpx u otros validadores, pueden añadirse al **toolchain del runner** sin abrir acceso a internals.

El runner ejecuta selectores concretos registrados, por ejemplo:

```text
e2e-runner run smoke
e2e-runner run surface-contract
```

`all` pertenece a `scripts/ci/run_e2e_platform.sh`, no al runner individual.

### 2.4 Runners especializados: excepción permitida

Se permite otro runner cuando cambia realmente la naturaleza de la herramienta:

```text
e2e-runner-python      journeys HTTP/system
load-runner-k6         load/performance
browser-runner         browser/UX
contract-runner        protocolo especializado
```

Cada runner especializado conserva por defecto el mismo boundary:

- no PostgreSQL;
- no Docker socket;
- no internals de aplicación;
- no credenciales de instalación.

Una suite nueva por sí sola no justifica un runner nuevo.

## 3. Suite registry: contrato declarativo

El registro canónico existe en:

`tests/system_e2e/suites.toml`

Cada suite habilitada declara como mínimo:

```text
name / description
selector
profiles
runtime services
fresh_world
fault_injection
cost class
artifact namespace
PR / merge / nightly / manual eligibility
enabled
```

El resolver está en:

`scripts/ci/e2e_suite_registry.py`

El ejecutor de una sola suite está en:

`scripts/ci/run_e2e_suite.sh <suite>`

El dispatcher de plataforma está en:

`scripts/ci/run_e2e_platform.sh <suite|all>`

Suites actualmente habilitadas:

```text
smoke
surface-contract
```

`tests/architecture/test_e2e_platform_contract.py` protege que:

- existan al menos dos suites habilitadas para demostrar reusabilidad real;
- cada suite tenga los campos obligatorios;
- artifact namespaces/selectors no colisionen;
- sólo se declaren services/profiles soportados;
- todo selector habilitado tenga implementación estática en el runner;
- el Dockerfile del runner no adquiera atajos hacia DB/application internals.

## 4. Semántica de `all`

`all` significa ejecutar todas las suites habilitadas, no ejecutar un test gigante ni compartir DB contaminada.

Implementación actual:

```text
build Request Engine image once
build e2e-runner image once

for each enabled suite:
    unique COMPOSE_PROJECT_NAME
    fresh PostgreSQL volume/world
    migrate
    runtime DB identities
    bootstrap trust root
    start declared runtime services
    execute black-box runner
    collect namespaced evidence
    destroy stack + volumes
```

El dispatcher no se detiene en el primer failure: continúa con las suites restantes para conservar evidencia completa y retorna failure agregado al final.

Las imágenes/layers se reutilizan; el estado autoritativo no.

Compartir mundo entre suites sería una optimización excepcional y explícita, nunca el default.

## 5. Cost model y selección de suites

Los system/E2E son caros. La plataforma permite seleccionar evidencia proporcional al riesgo.

Modelo objetivo:

```text
PR normal
    smoke + suites dirigidas por riesgo

merge-sensitive / cambios transversales
    smoke + conjunto conservador ampliado

nightly / manual / release candidate
    all
    f01
    fault/recovery
    oidc cuando corresponda
```

Durante la calibración actual, PR ejecuta `smoke`; las demás suites pueden pedirse por selector mediante `workflow_dispatch`/`workflow_call`.

Los campos `pr`, `merge`, `nightly` y `manual` ya viven en el registry, pero la policy automática que los consume todavía debe calibrarse antes de convertir lanes caros en required checks.

Path-based selection puede ahorrar costo, pero no puede ser la única protección para garantías transversales.

## 6. Redes y aislamiento

La topología actual usa redes explícitas:

```text
edge:
    e2e-runner
    api
    control-plane
    mailpit [sólo profile delivery]

backend (internal):
    api
    control-plane
    worker [profile]
    postgres
    vault [profile]
    mailpit [profile]
```

Propiedades actuales:

- PostgreSQL sólo está en `backend`;
- `e2e-runner` sólo está en `edge`;
- `backend` es `internal: true`;
- PostgreSQL no publica puerto al host en el Compose canónico;
- runner no monta Docker socket;
- runner no recibe DSNs de DB;
- runner comprueba que `request_engine` no sea importable;
- runner comprueba negativamente que `postgres:5432` no sea resolvible desde su red.

Estas comprobaciones aparecen como checkpoints del runner y están además protegidas por fitness checks estáticos.

No introducir `host.docker.internal`, `network_mode: host`, `extra_hosts` o bridges equivalentes que invaliden este boundary sin una excepción documentada.

## 7. Compose profiles y dependencias por suite

El Compose canónico ya contiene profiles opcionales:

```text
runner   -> e2e-runner
worker   -> worker
secrets  -> Vault dev
delivery -> Mailpit
```

El registry declara `profiles` y `services`; `run_e2e_suite.sh` resuelve esos valores y arranca los runtime services declarados por la suite.

El registry, no el test, debe decidir qué infraestructura opcional necesita una suite.

Authentik/OIDC todavía no está implementado en el Compose de referencia; `oidc` se mantiene como profile permitido/futuro del contrato, no como capability ya demostrada.

## 8. Bootstrap, migrations y estado de negocio

Setup privilegiado permitido para crear un mundo nuevo:

- `alembic upgrade head`;
- creación de logins/roles runtime;
- `request-engine-platform-bootstrap issue`;
- `request-engine-platform-bootstrap establish`.

Estas acciones usan la misma imagen Request Engine y credenciales de instalación separadas del runner.

Después del trust root, el estado de negocio de una suite system/E2E debe crearse mediante contratos soportados. No se permite SQL para fabricar el outcome principal del journey.

Una DB proof cuyo riesgo sea precisamente RLS/constraint/lock pertenece a otra taxonomía y puede usar SQL; eso no crea una excepción para journeys black-box.

## 9. Secret/state handoff

El bootstrap actual genera una contraseña efímera y no entrega al runner el bootstrap DSN/token.

Para suites largas todavía falta formalizar el handoff reusable de credenciales y estado entre fases. El contrato objetivo sigue siendo:

### Secretos

- enmascarar secretos dinámicos en GitHub cuando salgan del proceso que los crea;
- nunca secretos en argv, URL, labels, container names o artifacts;
- secret workspace separado de `.ci/docker-e2e/`;
- material reutilizable con permisos estrechos y destrucción garantizada.

### Estado de suite

Una suite multifase podrá usar un volumen/archivo efímero del runner para IDs/revisions no sensibles y un canal separado para secretos.

No usar PostgreSQL auxiliar como state bus del test.

## 10. Evidence por suite

Cada suite usa su propio namespace:

```text
.ci/docker-e2e/<artifact_namespace>/
    phases/
    services/
    docker/
    checkpoints.json
    metadata.json
    EVIDENCE_SCOPE.txt
```

El collector actual ya evita persistir:

- `docker compose config` crudo;
- `docker inspect` crudo.

En su lugar conserva:

- `compose-ps`;
- lista de services/images;
- versión Docker/Compose;
- proyección sanitizada de state/networks/mount destinations;
- logs por servicio;
- metadata acotada;
- redacción secundaria de Bearer/bootstrap tokens/DSN passwords/Vault token patterns.

JUnit separado e `isolation-proof.json` dedicado siguen siendo mejoras futuras; hoy la evidencia de aislamiento vive en `checkpoints.json` + container-state sanitizado.

## 11. Fault injection

El runner nunca recibe Docker socket. Fault injection pertenece al orquestador.

Contrato objetivo:

```text
runner prepares durable observable state
    ↓
runner emits checkpoint/barrier
    ↓
orchestrator kill/restart target service
    ↓
orchestrator waits health/readiness
    ↓
runner resumes and reconciles via public contract
```

El registry ya puede declarar `fault_injection`, pero el protocolo genérico de barrera/reanudación todavía no está implementado.

No usar `sleep` arbitrario como único coordinador de races.

## 12. F-01 como suite consumidora

F-01 sigue siendo el journey de aceptación más amplio de auth/authority/booking/recovery. Ya no define la infraestructura.

Mapeo normativo resumido:

```text
F01-01 clean bootstrap + platform login
F01-02 second security operator + platform provisioner
F01-03 organization + tenant controller
F01-04 tenant login + authority observation
F01-05 staff + AGENT/INTEGRATION identity/policy ceilings
F01-06 supply/capacity provisioning
F01-07 onboarding readiness for appointment journey
F01-08 operation/schema discovery + valid booking
F01-09 forged tenant/party/capability; no booking/outbox side effect
F01-10 local revocation + immediate denial
F01-11 governed recovery + delivery + lost-response reconciliation
F01-12 last-controller refusal + replacement + provenance
F01-13 prepare durable worker/API saga state
F01-14 worker crash/restart
F01-15 worker durable recovery/idempotency
F01-16 API crash/restart
F01-17 API/client reconciliation
F01-OIDC separate Native→OIDC suite/profile
```

El detalle normativo sigue en `auth-production-completion-plan.md`.

Si F-01 necesita SQL o internals para pasar, encontró un gap real de producto/deployment.

## 13. Taxonomía

```text
unit
    pytest in-process

module/integration
    componentes reales; Testcontainers cuando aporte valor

database proof
    PostgreSQL 18 directo cuando el riesgo sea DB/RLS/constraint/lock

system/E2E
    reusable Docker E2E platform + swappable black-box suite
```

Testcontainers no sustituye esta plataforma porque aquí la unidad bajo prueba es la instalación/topología completa.

## 14. Estado real del branch

### Implementado y demostrado

- imagen única Request Engine para migrate/bootstrap/API/control-plane y misma referencia de artifact para worker;
- PostgreSQL 18 separado;
- migrations + runtime roles + bootstrap desde mundo limpio;
- API/control-plane readiness real;
- imagen genérica `e2e-runner` separada de la aplicación;
- runner sin Request Engine package, DB DSN ni Docker socket;
- redes `edge/backend` con backend interno;
- suite registry versionado;
- selector de una suite;
- dispatcher `suite=<name|all>`;
- services/profiles resueltos desde el registry;
- fresh Compose project/world por suite;
- artifacts namespaceados por suite;
- collector estructuralmente sanitizado;
- isolation checks runtime;
- dos suites habilitadas (`smoke`, `surface-contract`) para proteger reusabilidad;
- `workflow_dispatch` y `workflow_call` reutilizables;
- fitness checks registry ↔ runner ↔ topology;
- Docker E2E exact-head verde para el lane `smoke`;
- Python quality/architecture exact-head verde después de introducir los nuevos guardrails.

### Implementado pero todavía requiere una demostración dedicada más fuerte

- `all` recorre todas las suites habilitadas con mundo limpio y failure agregado; la semántica está implementada, pero no se usa como default del PR durante calibración;
- `surface-contract` está registrado/implementado, pero no corre en cada PR (`pr=false`).

### Pendiente

1. minimizar DSNs/credenciales por proceso; el Compose aún usa un `x-common-env` demasiado amplio para API/control-plane;
2. secret/state handoff reusable para journeys multifase autenticados;
3. JUnit y `isolation-proof.json` dedicados si aportan mejor consumo de evidencia;
4. fault-injection protocol genérico con barriers;
5. provisionar worker Principal/publisher reales para suites worker;
6. F-01 completo como suite black-box;
7. Vault/Mailpit funcionalmente conectados a journeys, no sólo disponibles como profiles;
8. Authentik/OIDC lane;
9. policy automática PR/merge/nightly/all y calibración de coste/flakiness;
10. promoción eventual del Docker E2E desde `continue-on-error` a required cuando la señal sea estable.

## 15. Fases revisadas

| Fase | Entregable | Estado |
| --- | --- | --- |
| P0 | alcance/gating inicial | completado |
| P1 | imagen única RE + PostgreSQL separado + reference compose | implementado |
| P2a | clean install + readiness + evidencia básica | demostrado |
| P2b | evidence/secret hardening estructural | parcial: collector saneado; handoff reusable pendiente |
| P3a | generic runner + registry + selector + edge/backend + profiles + isolation | **implementado y demostrado** |
| P3b | fresh-world orchestration + namespaced evidence + `all` semantics + reusable workflow | **implementado; smoke demostrado, `all` dedicado aún por calibrar** |
| P4 | F-01 + worker/API fault injection | pendiente |
| P5 | suites dirigidas booking/authority/recovery/worker | pendiente según valor |
| P6 | OIDC/Authentik + subset CI-feasible de G | pendiente |
| P7 | coste/flakiness + selection policy + required checks | pendiente |

## 16. Definition of Done de la plataforma completa

El **core reusable** ya existe, pero la plataforma completa no se considera cerrada hasta demostrar:

1. una única imagen RE sirve migrate/bootstrap/API/control-plane/worker;
2. PostgreSQL está separado;
3. runner genérico ejecuta múltiples suites sin imagen específica por suite;
4. registry resuelve dependencies/profiles/selectores declarativamente;
5. `all` crea mundo limpio por suite;
6. runner no tiene DB DSN, DB network, app internals ni Docker socket;
7. isolation checks quedan como evidencia consumible;
8. business state system/E2E nace por contratos soportados;
9. fault injection queda en el orquestador;
10. artifacts sobreviven failures y están namespaced;
11. secretos no aparecen en artifacts/config/inspect crudos;
12. credenciales runtime se distribuyen need-to-know;
13. la misma invocación funciona localmente y en GitHub CI;
14. F-01 corre como suite ordinaria de la plataforma;
15. una suite normal puede añadirse sin copiar Compose/workflow;
16. `all` no crea dependencia de orden;
17. policy de coste/gating se calibra antes de hacer required los lanes caros.

## 17. Excepciones permitidas

La plataforma es el default para system/E2E, no una regla ciega.

Excepciones válidas pueden incluir:

- browser/load runner con toolchain distinto;
- prueba production-shaped externa que no cabe en GitHub-hosted runner;
- restore/backup/fencing que requiere entorno mayor;
- TLS/ingress externo;
- proveedor externo real cuya certificación no puede simularse;
- benchmark con hardware especializado.

Cada excepción debe explicar por qué la plataforma reusable no puede demostrar el riesgo, qué boundary alternativo usa y qué evidencia produce.

## 18. Qué CI puede y no puede certificar

### CI puede demostrar

- instalación reproducible desde cero;
- imagen única de Request Engine;
- runtime DB roles/surfaces;
- readiness;
- TCP real entre contenedores;
- aislamiento runner/backend;
- journeys black-box según suites implementadas;
- provisioning por contratos públicos cuando la suite lo ejerce;
- crash/restart cuando una suite futura lo implemente;
- Vault dev/Mailpit plumbing cuando la suite lo ejerza;
- OpenAPI/discovery/readiness observables.

### Fuera de CI normal

- TLS/ingress externo real;
- deliverability real de correo/SPF/DKIM/reputation;
- Vault HA/unseal/policies production-grade;
- backup/restore production-shaped + restore-fencing;
- human break-glass;
- RPO/RTO reales;
- SLOs de producción.

Un run verde no certifica esas propiedades.

## 19. Criterios de falsificación

La plataforma se considera rota aunque CI esté verde si:

- una suite system/E2E importa internals para crear/verificar su outcome principal;
- runner puede conectar PostgreSQL;
- suite obtiene IDs/revisions por SELECT por falta de API pública;
- worker usa principal/publisher inventado para pasar;
- rejected attack deja side effects;
- recovery lee secrets desde DB;
- crash/restart se sustituye por crear mundo nuevo;
- `all` comparte estado entre suites sin declaración/justificación;
- una suite nueva requiere copiar Compose/workflow sin necesidad topológica real;
- artifacts contienen secretos/DSNs/signing keys;
- una fase PASS no tiene oracle observable;
- se presenta Vault dev/Mailpit como producción lista.

## 20. Regla rectora final

La infraestructura E2E de Request Engine debe comportarse como una **plataforma de instalación + ejecución de suites**, no como un test gigante cableado a un único journey.

> **Deployment definition estable. Test workload intercambiable. Mundo limpio por suite. Black-box por defecto. Excepciones explícitas.**
