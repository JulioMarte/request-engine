# Plataforma reusable de E2E real en Docker para GitHub CI

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization`.

Estado: **arquitectura objetivo oficial para system/E2E tests; P1/P2 smoke base implementados y demostrados; plataforma reusable P3 en ejecución.** No es certificación ni autorización de despliegue a producción.

Este documento ya no define una infraestructura específica para F-01. Define la **plataforma reusable de CI E2E de Request Engine**. F-01 será una suite consumidora de esta plataforma, igual que suites futuras de booking, authority, recovery, worker, OIDC u otras capacidades cross-module.

El principio rector es:

> **El deployment bajo prueba es estable y reusable; el workload de prueba es intercambiable.**

`architecture/auth-production-completion-plan.md` sigue siendo la fuente normativa del contenido de F-01. Este documento define cómo ejecutar ese journey —y otros journeys futuros— de forma aislada, reproducible, black-box y falsificable.

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
     API                               ├── booking
     control-plane                     ├── authority
     worker                            ├── recovery
     Vault                             ├── worker
     Mailpit                           ├── f01
     [Authentik]                       ├── oidc
                                       └── all
```

La infraestructura no se duplica por suite. Existe **una definición de deployment E2E de referencia** y una definición separada de qué workload ejecutar.

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
suite registry
        ×
e2e-runner intercambiable
```

Las excepciones deben justificarse por una diferencia real de topología o dependencia externa, no por comodidad del test.

## 1. Qué hace reusable a la plataforma

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

Sobre ese stack se puede ejecutar cualquier suite compatible mediante el mismo contrato de runner.

Ejemplos conceptuales:

```text
run_e2e_suite smoke
run_e2e_suite booking
run_e2e_suite authority
run_e2e_suite recovery
run_e2e_suite worker
run_e2e_suite f01
run_e2e_suite oidc
run_e2e_suite all
```

El selector de suite no debe requerir modificar Compose ni el workflow para cada nueva feature normal.

## 2. Separación de responsabilidades

### 2.1 GitHub Actions / E2E orchestrator

GitHub Actions **orquesta infraestructura**, pero no implementa reglas de negocio del journey.

Responsabilidades:

- checkout;
- build de la única imagen de Request Engine;
- build de la imagen genérica `e2e-runner`;
- resolver la suite solicitada;
- activar Compose profiles requeridos por esa suite;
- levantar infraestructura;
- ejecutar migrations/bootstrap one-shot;
- arrancar superficies runtime;
- ejecutar isolation checks;
- lanzar el runner con la suite seleccionada;
- inyectar fallos de infraestructura cuando la suite lo declare;
- recoger evidencia siempre;
- publicar summary/JUnit/logs;
- destruir stack, volúmenes y secretos efímeros.

No debe crear entidades de negocio mediante SQL.

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

Son procesos/contenedores distintos cuando sus ciclos de vida lo requieren, pero salen del mismo artefacto inmutable. CI compara image ID/digest efectivo, no sólo tags.

PostgreSQL permanece separado.

### 2.3 Imagen genérica `e2e-runner`

`e2e-runner` es un artefacto de pruebas **genérico**, no “el runner F-01”. Debe contener sólo herramientas de consumidor black-box:

- Python/pytest;
- `httpx`;
- validadores de contrato;
- soporte de checkpoints/estado/JUnit;
- suites E2E registradas.

No instala el paquete de aplicación Request Engine sólo por comodidad. No copia `src/request_engine`, no usa `pip/uv install -e .`, no contiene `psycopg`/SQLAlchemy para fixtures, no recibe DSNs de PostgreSQL y no monta el Docker socket.

La imagen puede ejecutar distintas suites sin reconstruirse:

```bash
e2e-runner run smoke
e2e-runner run booking
e2e-runner run recovery
e2e-runner run f01
e2e-runner run all
```

La implementación concreta puede ser un entrypoint propio o un wrapper de pytest; la propiedad normativa es que la selección sea declarativa y no requiera una imagen distinta por suite ordinaria.

### 2.4 Runners especializados: excepción permitida

Se permite un runner distinto cuando la herramienta cambia de naturaleza, por ejemplo:

```text
e2e-runner-python      journeys HTTP/system
load-runner-k6         carga/performance
browser-runner         UX/browser cuando exista frontend soportado
contract-runner        protocolo/consumer contract específico
```

Cada runner especializado debe respetar el mismo boundary: **no PostgreSQL, no Docker socket, no internals de aplicación, no privilegios de instalación salvo contrato explícito**.

Una suite nueva no justifica por sí sola un runner nuevo.

## 3. Suite registry: contrato declarativo

La plataforma tendrá un registro de suites versionado en el repo. El formato exacto puede evolucionar (`toml`, YAML o Python data cerrada), pero debe declarar como mínimo:

```text
suite name
human description
test selector / markers
required services/profiles
whether fresh world is required
whether fault injection is required
expected maximum class of cost/time
artifact namespace
whether suite is eligible for PR / merge / nightly / manual
```

Ejemplo conceptual:

```toml
[suites.smoke]
selector = "smoke"
requires = ["api", "control-plane"]
fault_injection = false
fresh_world = true

[suites.booking]
selector = "booking"
requires = ["api", "control-plane"]
fault_injection = false
fresh_world = true

[suites.recovery]
selector = "recovery"
requires = ["api", "control-plane", "worker", "vault", "mailpit"]
fault_injection = true
fresh_world = true

[suites.f01]
selector = "f01"
requires = ["api", "control-plane", "worker", "vault", "mailpit"]
fault_injection = true
fresh_world = true

[suites.oidc]
selector = "oidc"
requires = ["api", "control-plane", "authentik"]
fresh_world = true
manual_or_scheduled = true
```

El workflow no debe contener un árbol grande de lógica específica de features. Debe consultar/resolver el registry mediante un script repository-local estrecho, por ejemplo:

```text
scripts/ci/run_e2e_suite.sh <suite>
```

o equivalente Python tipado.

## 4. Semántica de `all`

`all` significa **ejecutar todas las suites seleccionadas**, no compartir una base de datos contaminada entre ellas.

Por defecto:

```text
build application image once
build runner image once

for each suite:
    create fresh Compose project/world
    migrate/bootstrap
    run suite
    collect namespaced evidence
    destroy volumes/world
```

Esta política previene dependencia del orden:

```text
suite A leaves state
suite B accidentally depends on A
suite C only passes after B
```

Compartir mundo entre suites es una optimización excepcional. Requiere una agrupación explícita cuya independencia haya sido demostrada y no puede ser el default de `all`.

Las capas/imágenes Docker sí se reutilizan entre suites; el estado autoritativo no.

## 5. Cost model y selección de suites

Los system/E2E son caros. La plataforma debe permitir ejecutar sólo la evidencia proporcional al riesgo sin perder una ruta conservadora.

Modelo objetivo:

```text
PR normal
    smoke + suites dirigidas por riesgo

merge-sensitive / cambios transversales
    smoke + conjunto conservador ampliado

nightly / manual / release candidate
    all
    f01
    fault/recovery suites
    oidc cuando corresponda
```

Path-based selection puede ahorrar costo, pero **no puede ser la única protección** para garantías transversales. Cambios en migrations, auth/authority, tenancy, shared runtime, operation catalog o worker pueden obligar suites adicionales aunque el path local parezca pequeño.

El suite registry y/o una policy de selección debe ser explícita y revisable; no esconderla en condiciones dispersas del YAML de Actions.

## 6. GitHub Actions reusable interface

El workflow debe tender a una interfaz reusable, con `workflow_dispatch` y eventualmente `workflow_call`:

```text
suite: smoke | booking | authority | recovery | worker | f01 | oidc | all
fault_mode: default | none | suite-defined
retain_evidence: normal | extended
```

No todos estos inputs tienen que exponerse desde el primer commit. La propiedad importante es que el workflow sea un **orquestador parametrizado**, no un script monolítico F-01.

Ejemplo conceptual:

```yaml
workflow_dispatch:
  inputs:
    suite:
      type: choice
      options: [smoke, booking, authority, recovery, worker, f01, oidc, all]
```

Otros workflows pueden invocar la plataforma sin duplicar su implementación.

## 7. Redes, puertos y aislamiento

La plataforma usa al menos dos redes explícitas:

```text
edge/test:
    e2e-runner
    api
    control-plane
    [mailpit HTTP si la suite lo necesita]

backend:
    api
    control-plane
    worker
    postgres
    vault
    mailpit SMTP
```

Reglas:

- `postgres` no pertenece a `edge/test`;
- `e2e-runner` no pertenece a `backend`;
- no depender de la red `default` implícita para servicios protegidos;
- CI no publica PostgreSQL al host;
- sin `host.docker.internal`, `network_mode: host` ni `extra_hosts` que puentearían el aislamiento;
- API/control-plane sólo publican host ports en profiles de debug/smoke que lo justifiquen;
- journey black-box usa DNS interno;
- Vault no se expone al runner;
- Mailpit HTTP sólo se expone al runner cuando una suite de plumbing necesita inspeccionarlo.

Antes de cualquier suite black-box, CI prueba negativamente:

1. runner no puede resolver/conectar `postgres:5432`;
2. runner no recibe `*_DATABASE_URL`, `PG*` ni migration DSNs;
3. `import request_engine` no está disponible como aplicación instalada;
4. no existe `/var/run/docker.sock`;
5. inspect sanitizado confirma que el runner sólo está en redes autorizadas.

## 8. Compose profiles y dependencias por suite

No todas las suites necesitan todo el stack.

La definición Compose puede usar profiles para dependencias opcionales:

```text
base:
    postgres
    api
    control-plane

worker profile:
    worker

secrets profile:
    vault

delivery profile:
    mailpit

oidc profile:
    authentik
```

Ejemplos:

```text
booking  -> base
recovery -> base + worker + secrets + delivery
f01      -> base + worker + secrets + delivery
oidc     -> base + oidc
```

El suite registry decide qué profiles necesita; el test no manipula infraestructura directamente.

## 9. Bootstrap, migrations y estado de negocio

Un mundo nuevo necesita setup privilegiado antes de que exista una API autenticable.

Setup de infraestructura permitido:

- `alembic upgrade head`;
- creación de logins/roles runtime;
- `request-engine-platform-bootstrap issue`;
- `request-engine-platform-bootstrap establish`.

Estas acciones one-shot usan la misma imagen Request Engine y credenciales de instalación separadas.

Después del trust root, el estado de negocio de una suite system/E2E debe crearse mediante contratos soportados. No se permite usar SQL para fabricar el resultado principal que la suite pretende probar.

Una suite de DB cuyo riesgo **es precisamente** un constraint/RLS/lock puede usar SQL porque pertenece a otra clase de evidencia. Esa es una excepción de taxonomía, no una excepción para los journeys black-box.

## 10. Secret/state handoff

### Secretos

- secretos dinámicos se enmascaran inmediatamente en GitHub;
- bootstrap token se consume durante `establish` y no llega al runner;
- passwords/proofs reutilizables usan secrets/files efímeros con permisos estrechos;
- nunca secretos en argv, URL, labels, container names o artifacts;
- secret workspace separado de `.ci/docker-e2e/` y destruido siempre.

### Estado de suite

Una suite multifase puede usar un volumen efímero `e2e-state` accesible sólo al runner:

- IDs/revisions no sensibles en `state.json`;
- material secreto separado con permisos 0600;
- reautenticación por API preferida a persistir bearer tokens;
- artifact `checkpoints.json` se genera desde una vista sanitizada;
- nada de tablas auxiliares de PostgreSQL como state bus del test.

Cada suite obtiene su propio state volume/world salvo excepción explícita.

## 11. Evidence namespace por suite

Los artifacts se namespacean por suite:

```text
.ci/docker-e2e/
├── platform/
│   ├── build/
│   └── metadata/
├── smoke/
│   ├── summary.md
│   ├── junit.xml
│   ├── checkpoints.json
│   ├── isolation-proof.json
│   ├── services/
│   └── docker/
├── booking/
├── recovery/
├── f01/
└── oidc/
```

Un run `all` no mezcla resultados indistinguibles. Debe ser posible responder:

```text
qué suite falló
qué checkpoint falló
qué servicio estaba implicado
qué image SHA se probó
qué pasó antes/después
```

No se sube `docker compose config` o `docker inspect` crudo si contiene environment/secret material. Se generan proyecciones sanitizadas antes de persistir artifacts.

## 12. Fault injection

El runner nunca recibe Docker socket. La suite declara que necesita fault injection; el orquestador ejecuta la acción.

Patrón:

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

Se aplica a worker, API u otros procesos cuando el contrato de la suite lo requiera.

No `sleep` arbitrario como único coordinador de races. Usar condición observable, barrier/test hook acotado o evento durable que no cambie la semántica bajo prueba.

## 13. F-01 como suite consumidora de la plataforma

F-01 sigue siendo el journey de aceptación más amplio de auth/authority/booking/recovery. Ya no define la plataforma.

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

El detalle normativo sigue en `auth-production-completion-plan.md`; ninguna simplificación de este documento reduce ese alcance.

Si F-01 necesita SQL o internals para pasar, encontró un gap real de producto/deployment.

## 14. Taxonomía de pruebas

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

Testcontainers no sustituye a esta plataforma porque aquí la unidad bajo prueba es la instalación/topología completa. Puede seguir siendo la mejor herramienta para integration tests más pequeños.

## 15. Estado real del branch

### Ya demostrado

- una imagen Request Engine sirve migrate/API/control-plane y resuelve worker al mismo artifact;
- PostgreSQL 18 separado;
- migrations + runtime logins + bootstrap desde mundo limpio;
- API/control-plane readiness real;
- host TCP smoke;
- evidencia básica/artifacts;
- check experimental durante calibración.

### Aún pendiente para declarar la plataforma reusable implementada

1. imagen genérica `e2e-runner`;
2. suite registry;
3. selector/orquestador `suite=<name|all>`;
4. redes `edge/backend`;
5. Compose profiles por dependencias opcionales;
6. minimización de env/credenciales por servicio;
7. secret/state handoff seguro;
8. isolation proof automatizado;
9. artifacts namespaceados por suite;
10. sanitización estructural de compose/inspect;
11. fresh-world orchestration por suite;
12. fault-injection protocol genérico;
13. F-01 implementado como primera suite amplia;
14. reusable/manual workflow interface;
15. policy de selección PR/merge/nightly/all calibrada.

El hecho de que el smoke actual esté verde no significa que estos puntos ya existan.

## 16. Fases revisadas

| Fase | Entregable |
| --- | --- |
| P0 | alcance/gating inicial: completado |
| P1 | imagen única RE + PostgreSQL separado + reference compose: baseline implementado |
| P2a | host smoke/readiness/evidencia básica: demostrado |
| P2b | evidence + secret hardening |
| P3a | **plataforma reusable**: generic runner + suite registry + selector + edge/backend + profiles + isolation |
| P3b | fresh-world orchestration + namespaced evidence + `all` semantics |
| P4 | F-01 como primera suite amplia + worker/API fault injection |
| P5 | suites adicionales dirigidas: booking/authority/recovery/worker según valor |
| P6 | OIDC/Authentik y subconjunto CI-feasible de G |
| P7 | calibración de coste/flakiness + policy PR/merge/nightly + required checks |

## 17. Definition of Done de la plataforma

La plataforma reusable no está terminada hasta demostrar en exact-head CI:

1. una única imagen RE sirve migrate/bootstrap/API/control-plane/worker;
2. PostgreSQL está separado;
3. `e2e-runner` genérico puede ejecutar al menos dos suites distintas sin reconstrucción específica;
4. suite registry resuelve dependencias/profiles/selectores de forma declarativa;
5. `suite=all` crea mundo limpio por suite por defecto;
6. runner no tiene DB DSN, DB network, internals de aplicación ni Docker socket;
7. isolation proof automatizado queda como evidencia;
8. estado de negocio system/E2E nace por contratos soportados;
9. fault injection queda en el orquestador, no en el runner;
10. artifacts están namespaceados por suite y sobreviven a failure;
11. secretos no aparecen en artifacts/config/inspect crudos;
12. credenciales runtime se distribuyen need-to-know;
13. misma invocación de suite funciona localmente y en GitHub CI;
14. F-01 corre como suite, no como implementación especial del workflow;
15. una suite nueva normal puede añadirse sin copiar Compose ni duplicar workflow;
16. `all` no crea dependencia de orden entre suites;
17. policy de coste/gating está documentada y calibrada antes de hacer checks caros required.

## 18. Excepciones permitidas

La plataforma es el default ideal para system/E2E, no una religión.

Excepciones válidas pueden incluir:

- browser/load runner con toolchain distinto;
- prueba production-shaped externa que no cabe en GitHub-hosted runner;
- restore/backup/fencing que necesita entorno aislado mayor;
- TLS/ingress externo;
- proveedor externo real cuya certificación no puede simularse;
- benchmark que necesita hardware especializado.

Cada excepción debe explicar **por qué la plataforma reusable no puede demostrar el riesgo**, qué boundary alternativo usa y qué evidencia produce. No se acepta una excepción sólo para evitar implementar una API pública que el producto necesita.

## 19. Qué CI puede y no puede certificar

### CI puede demostrar

- instalación reproducible desde cero;
- imagen única de Request Engine;
- runtime DB roles/surfaces;
- readiness;
- TCP real entre contenedores;
- journeys black-box swappeables;
- provisioning por contratos públicos;
- booking/authority/recovery/etc. según suite;
- worker/API crash/restart cuando la suite lo exige;
- Vault dev/Mailpit plumbing;
- OpenAPI/discovery/readiness observables.

### Sigue fuera de CI normal

- TLS/ingress externo real;
- deliverability real de correo/SPF/DKIM/reputation;
- Vault HA/unseal/policies production-grade;
- backup/restore production-shaped + restore-fencing;
- human break-glass;
- RPO/RTO reales;
- SLOs de producción.

Un run verde no certifica esas propiedades.

## 20. Criterios de falsificación

La plataforma se considera rota aunque CI esté verde si:

- una suite system/E2E importa internals para crear/verificar el outcome principal;
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

## 21. Regla rectora final

La infraestructura E2E de Request Engine debe comportarse como una **plataforma de instalación + ejecución de suites**, no como un test gigante cableado a un único journey.

> **Deployment definition estable. Test workload intercambiable. Mundo limpio por suite. Black-box por defecto. Excepciones explícitas.**
