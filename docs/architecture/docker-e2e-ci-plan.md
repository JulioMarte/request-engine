# Plan de E2E real en Docker dentro de GitHub CI

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization`.

Estado: **P1/P2 implementados y smoke base validado; P3 en ejecución.** Este documento define el diseño normativo para completar F-01 y el subconjunto CI-feasible de G. No es certificación ni autorización de despliegue a producción.

El cambio principal respecto al plan inicial es deliberado: **F-01 no se ejecutará desde el host de GitHub ni tendrá acceso a PostgreSQL. Se ejecutará desde un contenedor `e2e-runner` aislado que sólo pueda hablar con las superficies públicas necesarias de Request Engine.**

Este diseño complementa `architecture/auth-production-completion-plan.md` (§11 y §12) y `architecture/sequential-completion-plan.md`.

## 0. Decisión arquitectónica

La topología de referencia queda conceptualmente así:

```text
                              Docker Compose

                 edge/test network
       ┌──────────────────────────────────────┐
       │                                      │
       │  e2e-runner                          │
       │  pytest + httpx                      │
       │      │                               │
       │      ├──────────────► api            │
       │      └──────────────► control-plane  │
       │                                      │
       └──────────────────┬───────────────────┘
                          │
                          │ runtime boundary
                          ▼
                 backend network
       ┌──────────────────────────────────────┐
       │ api / control-plane                  │
       │ worker                               │
       │ PostgreSQL 18                        │
       │ Vault                                │
       │ SMTP catcher                         │
       └──────────────────────────────────────┘
```

La propiedad importante no es estética: **`e2e-runner` no tendrá ruta de red a PostgreSQL, credenciales de PostgreSQL, acceso al Docker socket ni dependencias internas del dominio suficientes para saltarse la API.**

El test debe demostrar que un consumidor externo puede operar Request Engine desde un deployment nuevo mediante sus contratos publicados.

## 1. Por qué este plan sustituye al runner-host original

El plan inicial ejecutaba pytest/curl desde el host de GitHub contra puertos publicados en `localhost`. Eso prueba TCP real, pero deja demasiada libertad al harness: puede recibir accidentalmente una DSN, importar helpers internos o terminar creando fixtures por SQL.

El nuevo diseño convierte parte del aislamiento en una propiedad de infraestructura:

1. **Black-box real:** el journey habla HTTP/TCP con `api` y `control-plane` por nombre de servicio.
2. **Sin acceso accidental a DB:** `e2e-runner` no pertenece a la red backend donde vive PostgreSQL.
3. **Sin Docker socket:** el test no recibe autoridad administrativa sobre el host.
4. **Sin código interno como atajo:** el runner debe depender de contratos HTTP, no repositories/services internos.
5. **Reproducible localmente:** la misma suite corre mediante Compose en laptop y GitHub Actions.
6. **Diagnóstico más honesto:** un failure del journey significa fallo observable desde fuera, no una inconsistencia de un helper in-process.

El coste es algo más de complejidad en Compose y en el manejo explícito de bootstrap/checkpoints. Esa complejidad está justificada porque F-01 es un system test, no un integration test pequeño.

## 2. Separación de responsabilidades

### 2.1 Orquestador GitHub Actions

GitHub Actions **orquesta**, pero no ejecuta las reglas de negocio del journey.

Responsabilidades:

- checkout;
- build de la imagen única de Request Engine;
- levantar infraestructura;
- ejecutar migrations/bootstrap one-shot;
- arrancar servicios runtime;
- lanzar `e2e-runner`;
- inyectar fallos de infraestructura controlados (`kill`/`restart` worker);
- recoger evidencia siempre;
- publicar summary/JUnit/logs;
- tear-down.

No debe crear entidades de negocio mediante SQL.

### 2.2 Imagen única de Request Engine

Se mantiene la decisión de **build once**:

```text
request-engine:<git-sha>
        ├── migrate
        ├── platform bootstrap CLI
        ├── API
        ├── control-plane
        └── worker
```

Son procesos/contenedores separados cuando sus ciclos de vida lo requieren, pero salen del mismo artefacto inmutable.

PostgreSQL sigue siendo otro contenedor y nunca se empaqueta dentro de la imagen de Request Engine.

### 2.3 `e2e-runner`

`e2e-runner` es un artefacto de pruebas separado. Debe contener sólo lo necesario para comportarse como consumidor:

- Python/pytest;
- `httpx`;
- validadores de contratos cuando hagan falta;
- la suite `tests/e2e_docker/` o un paquete de test equivalente.

No debe necesitar:

- `psycopg`/SQLAlchemy para fixtures;
- DSN de PostgreSQL;
- `SET ROLE`;
- repositories de Request Engine;
- servicios internos del dominio;
- funciones de migración;
- Docker socket.

Si una transición requerida por F-01 no puede realizarse por una superficie pública soportada, eso se registra como **gap de producto** y se corrige en Request Engine. No se puenteará desde el test con SQL.

## 3. Redes y exposición

La suite debe utilizar al menos dos redes lógicas:

```text
edge/test network:
    e2e-runner
    api
    control-plane
    [mailpit HTTP sólo si el journey necesita verificar captura]

backend network:
    api
    control-plane
    worker
    postgres
    vault
    [mailpit SMTP]
```

Reglas:

- `postgres` no se conecta a `edge/test`.
- `e2e-runner` no se conecta a `backend`.
- CI no necesita publicar PostgreSQL al host.
- los puertos de API/control-plane sólo se publican cuando sean útiles para debug local; no son requisito para el journey CI.
- las aserciones de Mailpit deben usar únicamente su API de prueba; nunca se interpretan como certificación de deliverability.

## 4. Bootstrap y provisioning inicial

F-01 no puede eliminar la ceremonia inicial privilegiada: un deployment vacío necesita migrations, roles runtime y trust root antes de que exista una API autenticable.

Por tanto se distinguen dos categorías:

### Setup de infraestructura permitido

- `alembic upgrade head`;
- creación de logins/roles runtime;
- `request-engine-platform-bootstrap issue`;
- `request-engine-platform-bootstrap establish`.

Estas acciones son one-shot, usan la misma imagen de Request Engine y pueden acceder a backend/PostgreSQL porque forman parte de la instalación del sistema.

### Estado de negocio prohibido por SQL

Después del trust root, todo lo siguiente debe nacer mediante contratos soportados:

- segundo operador/provisioner;
- organización/tenant;
- tenant root;
- staff;
- agent/integration/workload principal;
- supply/capacity;
- booking;
- revocación;
- recovery;
- autoridad/controladores adicionales.

No se acepta un fixture SQL para que el journey “llegue” a un estado conveniente.

## 5. F-01 como journey con checkpoints

F-01 no debe convertirse en un único test monolítico de cientos de líneas. El journey se divide en checkpoints observables dentro del mismo mundo efímero:

```text
F01-01 bootstrap/login
F01-02 segundo operador / platform provisioner
F01-03 organización/tenant + Native tenant root
F01-04 login tenant root
F01-05 staff lifecycle
F01-06 agent/integration/workload identity
F01-07 supply/capacity
F01-08 booking normal
F01-09 booking adversarial / invariants
F01-10 revocation
F01-11 recovery
F01-12 last-controller protection/continuity
F01-13 enqueue durable worker work
F01-14 worker crash
F01-15 worker restart + durable recovery
```

Cada checkpoint debe emitir:

- nombre estable;
- start/end timestamp;
- PASS/FAIL;
- IDs de recursos no sensibles útiles para diagnóstico;
- `correlation_id`/request-id cuando exista;
- duración;
- mensaje de error sanitizado.

El summary del run debe poder indicar exactamente dónde murió el journey.

## 6. Crash/restart del worker

`e2e-runner` **no recibe `/var/run/docker.sock`**.

La inyección de fallo pertenece al orquestador GitHub/Compose:

```text
1. e2e-runner crea trabajo durable por API
2. GitHub/Compose confirma checkpoint preparado
3. GitHub ejecuta `docker compose kill worker`
4. GitHub ejecuta `docker compose start worker`
5. e2e-runner verifica por API el resultado/recovery
```

Así se conserva la separación:

- el cliente prueba comportamiento público;
- el orquestador controla infraestructura;
- el worker demuestra durabilidad/reanudación.

No se arrancará un worker falso con `WORKER_PRINCIPAL_ID` inventado o publisher dummy sólo para producir verde. El principal y las capacidades del worker deben provenir de provisioning soportado en el journey o de una ceremonia runtime explícitamente documentada.

## 7. Compose de referencia objetivo

Servicios:

```text
postgres             PostgreSQL 18
migrate              one-shot, misma imagen Request Engine
bootstrap            one-shot, misma imagen Request Engine
vault                dev mode sólo para plumbing
mailpit               SMTP catcher + API de inspección
api                   misma imagen Request Engine
control-plane         misma imagen Request Engine
worker                misma imagen Request Engine, profile/arranque controlado
e2e-runner            imagen mínima de pruebas black-box
[authentik]           job/profile separado para Native→OIDC
```

`depends_on`/healthchecks se usan para dependencias técnicas, pero readiness del sistema se sigue validando explícitamente. `migrate` y `bootstrap` deben terminar con `service_completed_successfully`; los servicios runtime deben alcanzar health/readiness real.

## 8. Estrategia de pruebas por nivel

No todo debe ir a este Compose.

```text
unit tests
    pytest in-process

integration tests pequeños
    pytest + dependencias efímeras/Testcontainers cuando aporten valor

system/E2E F-01
    Docker Compose + e2e-runner black-box
```

Testcontainers es apropiado para componentes o adapters que necesitan una dependencia real aislada. No sustituye al Compose F-01 porque aquí la unidad bajo prueba es una **topología completa** con varios procesos, bootstrap, worker lifecycle y fault injection.

## 9. GitHub Actions objetivo

Esqueleto conceptual:

```yaml
- checkout
- build request-engine:<sha> once
- build e2e-runner
- docker compose up postgres vault mailpit
- run migrate one-shot
- run bootstrap one-shot
- docker compose up api control-plane
- wait readiness
- docker compose run --rm e2e-runner <F01 pre-worker checkpoints>
- provision/start worker when its real identity exists
- docker compose run --rm e2e-runner <prepare durable work>
- docker compose kill worker
- docker compose start worker
- docker compose run --rm e2e-runner <verify recovery>
- collect evidence always
- upload artifact always
- teardown always
```

El workflow actual de smoke se conserva como base mientras P3 migra el journey al runner aislado.

## 10. Evidencia y observabilidad obligatorias

Un failure debe permitir contestar **qué falló, en qué checkpoint, en qué servicio, con qué correlación y qué pasó inmediatamente antes/después**.

Artefacto objetivo:

```text
.ci/docker-e2e/
├── summary.md
├── metadata.json
├── junit.xml
├── checkpoints.json
├── request-engine-image.json
├── EVIDENCE_SCOPE.txt
├── phases/
│   ├── build.log
│   ├── infrastructure.log
│   ├── migrate.log
│   ├── bootstrap.log
│   ├── readiness.log
│   ├── journey.log
│   └── worker-recovery.log
├── services/
│   ├── postgres.log
│   ├── api.log
│   ├── control-plane.log
│   ├── worker.log
│   ├── vault.log
│   └── mailpit.log
└── docker/
    ├── compose-ps.txt
    ├── compose-config.txt
    └── inspect.json
```

Propiedades:

- recolección `if: always()` y best-effort;
- logs con timestamps;
- logs por servicio, no sólo un `compose.log` gigante;
- metadata del SHA/run/attempt;
- JUnit del runner;
- checkpoint summary;
- redacción de tokens/passwords/Authorization headers/recovery material;
- retention limitada;
- GitHub Step Summary compacto con PASS/FAIL por fase/checkpoint.

## 11. Qué prueba y qué NO prueba

### Evidencia válida en CI

- imagen única reproducible de Request Engine;
- migrations + bootstrap desde cero;
- readiness de superficies runtime;
- HTTP/TCP real desde otro contenedor;
- provisioning sin SQL fixtures;
- journeys multi-actor/authority;
- booking/capacity/revocation/recovery observables;
- worker crash/restart y recuperación durable;
- wiring de Vault dev y SMTP catcher;
- OpenAPI/readiness/pools que puedan observarse en el deployment.

### Fuera de alcance / D6

- TLS/ingress validado externamente;
- deliverability real de correo, SPF/DKIM/reputación;
- Vault production mode, HA, unseal y políticas production-grade;
- backup/restore production-shaped + restore-fencing;
- break-glass humano;
- RPO/RTO reales;
- SLOs de producción.

Un run verde **no** debe presentarse como certificación de esas propiedades.

## 12. Fases revisadas

| Fase | Estado / entregable |
| --- | --- |
| P0 | Decisión de alcance/gating: completada; check experimental durante calibración |
| P1 | Imagen única RE + PostgreSQL separado + compose + migrate + runtime roles: implementado |
| P2 | Docker smoke CI + readiness + evidencia/logs: implementado; smoke base verde |
| P3a | Añadir imagen/contenedor `e2e-runner` y redes `edge/backend` |
| P3b | Implementar F01-01→F01-12 black-box, sin SQL fixtures |
| P4 | Provisionar worker real + F01-13→15 crash/restart/recovery |
| P5 | Vault dev + Mailpit: stage/publish/reconcile y assertions de plumbing |
| P6 | Subconjunto G + Authentik separado/opt-in cuando corresponda |
| P7 | Calibrar flakiness, retirar `continue-on-error`, promover a required check |

## 13. Definition of Done

P3/P4 no están terminados hasta que se pueda demostrar todo lo siguiente en exact-head CI:

1. un único artefacto de Request Engine sirve migrate/bootstrap/API/control-plane/worker;
2. PostgreSQL corre separado;
3. `e2e-runner` corre en su propio contenedor;
4. `e2e-runner` no tiene DB DSN, acceso de red a PostgreSQL ni Docker socket;
5. el estado de negocio de F-01 se crea por CLI inicial + APIs soportadas, no fixtures SQL;
6. F01-01→15 reportan checkpoints claros;
7. worker crash/restart demuestra recuperación durable real;
8. JUnit, logs, inspect, metadata y summaries sobreviven incluso a failure;
9. secretos/material sensible no aparecen en artifacts;
10. un desarrollador puede reproducir localmente el mismo journey con Compose;
11. el check ha sido calibrado suficientemente antes de hacerlo requerido;
12. `EVIDENCE_SCOPE.txt` deja explícito qué propiedades continúan fuera de CI.

## 14. Evaluación honesta del cambio de plan

Este diseño es **mejor que el plan original para F-01** porque reduce los falsos positivos causados por un harness demasiado privilegiado. El plan anterior seguía siendo válido como smoke de deployment y por eso se conserva esa capa, pero no es la frontera adecuada para certificar un customer/system journey.

El nuevo `e2e-runner` introduce trabajo adicional (imagen de test, redes, manejo de checkpoints y coordinación del worker), pero ese trabajo compra propiedades útiles: aislamiento verificable, reproducibilidad y una prueba mucho más cercana a cómo un consumidor externo realmente usa Request Engine.

La regla rectora queda así:

> **Si F-01 necesita acceso a PostgreSQL o a internals para poder pasar, F-01 ha encontrado un gap del producto o del deployment. El test no debe esconderlo.**
