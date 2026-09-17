# Plan de E2E real en Docker dentro de GitHub CI

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization`.

Estado: **P1/P2 smoke base implementados y demostrados; P3 en ejecución.** Este documento define el diseño normativo para completar F-01 y el subconjunto CI-feasible de G. No es certificación ni autorización de despliegue a producción.

El cambio principal respecto al plan inicial es deliberado: **F-01 no se ejecutará desde el host de GitHub ni tendrá acceso a PostgreSQL. Se ejecutará desde un contenedor `e2e-runner` aislado que sólo pueda hablar con las superficies públicas necesarias de Request Engine.**

Este diseño complementa `architecture/auth-production-completion-plan.md` (§11 y §12) y `architecture/sequential-completion-plan.md`. Cuando este documento resuma F-01, el contrato normativo de `auth-production-completion-plan.md` sigue siendo la fuente de verdad; este plan debe mapearlo 1:1 y no reducir su alcance.

## 0. Decisión arquitectónica

La topología objetivo queda conceptualmente así:

```text
                              Docker Compose

                 edge/test network
       ┌──────────────────────────────────────────┐
       │                                          │
       │  e2e-runner                              │
       │  pytest + httpx                          │
       │      │                                   │
       │      ├──────────────► api                │
       │      ├──────────────► control-plane      │
       │      └──────────────► mailpit HTTP (*)   │
       │                                          │
       └──────────────────────┬───────────────────┘
                              │
                              │ runtime boundary
                              ▼
                 backend network (no test runner)
       ┌──────────────────────────────────────────┐
       │ api / control-plane                      │
       │ worker                                   │
       │ PostgreSQL 18                            │
       │ Vault                                    │
       │ Mailpit SMTP                             │
       └──────────────────────────────────────────┘

(*) sólo cuando una assertion de plumbing necesite inspeccionar el catcher.
```

La propiedad importante no es estética: **`e2e-runner` no tendrá ruta de red a PostgreSQL, credenciales de PostgreSQL, acceso al Docker socket, acceso al filesystem de la app ni dependencias internas suficientes para saltarse la API.**

El test debe demostrar que un consumidor externo puede operar Request Engine desde un deployment nuevo mediante contratos publicados.

## 1. Por qué este plan sustituye al runner-host original

El plan inicial ejecutaba pytest/curl desde el host de GitHub contra puertos publicados en `localhost`. Eso prueba TCP real, pero deja demasiada libertad al harness: puede recibir accidentalmente una DSN, importar helpers internos o terminar creando fixtures por SQL.

El nuevo diseño convierte parte del aislamiento en una propiedad de infraestructura:

1. **Black-box real:** el journey habla HTTP/TCP con `api` y `control-plane` por nombre de servicio.
2. **Sin acceso accidental a DB:** `e2e-runner` no pertenece a la red backend donde vive PostgreSQL.
3. **Sin Docker socket:** el test no recibe autoridad administrativa sobre el host.
4. **Sin código interno como atajo:** el runner depende de contratos HTTP, no repositories/services internos.
5. **Reproducible localmente:** la misma suite corre mediante Compose en laptop y GitHub Actions.
6. **Diagnóstico más honesto:** un failure del journey significa fallo observable desde fuera, no una inconsistencia de un helper in-process.
7. **Falsificabilidad estructural:** CI prueba negativamente que el runner no puede resolver/conectar a PostgreSQL ni importar Request Engine como librería de aplicación.

El coste es algo más de complejidad en Compose y en el manejo explícito de bootstrap/checkpoints. Esa complejidad está justificada porque F-01 es un system test, no un integration test pequeño.

## 2. Separación de responsabilidades

### 2.1 Orquestador GitHub Actions

GitHub Actions **orquesta infraestructura**, pero no ejecuta reglas de negocio del journey.

Responsabilidades:

- checkout;
- build de la imagen única de Request Engine;
- build de la imagen mínima `e2e-runner`;
- levantar infraestructura;
- ejecutar migrations/bootstrap one-shot;
- arrancar servicios runtime;
- lanzar fases del `e2e-runner`;
- inyectar fallos de infraestructura controlados (`kill`/`restart` worker y API);
- recoger evidencia siempre;
- publicar summary/JUnit/logs;
- tear-down y destrucción de volúmenes/secretos efímeros.

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

Son procesos/contenedores separados cuando sus ciclos de vida lo requieren, pero salen del mismo artefacto inmutable. CI debe comparar el image ID/digest efectivo, no sólo el tag declarado.

PostgreSQL sigue siendo otro contenedor y nunca se empaqueta dentro de la imagen de Request Engine.

### 2.3 `e2e-runner`

`e2e-runner` es un artefacto de pruebas separado. Debe contener sólo lo necesario para comportarse como consumidor:

- Python/pytest;
- `httpx`;
- validadores de contrato cuando hagan falta;
- la suite `tests/e2e_docker/` o paquete equivalente;
- utilidades pequeñas para checkpoints/JUnit.

No debe contener ni instalar el paquete de aplicación Request Engine sólo por comodidad. El Dockerfile del runner debe copiar un manifiesto de dependencias de E2E y la suite, **no `src/request_engine` completo ni `pip/uv install -e .`**.

No debe necesitar:

- `psycopg`/SQLAlchemy para fixtures;
- DSN de PostgreSQL;
- `SET ROLE`;
- repositories de Request Engine;
- servicios internos del dominio;
- funciones de migración;
- Docker CLI/socket;
- bind mounts del source tree de la aplicación.

Si una transición requerida por F-01 no puede realizarse por una superficie pública soportada, eso se registra como **gap de producto** y se corrige en Request Engine. No se puenteará desde el test con SQL ni imports internos.

## 3. Redes, puertos y exposición

La suite debe utilizar al menos dos redes explícitas:

```text
edge/test:
    e2e-runner
    api
    control-plane
    [mailpit HTTP sólo cuando sea necesario]

backend:
    api
    control-plane
    worker
    postgres
    vault
    mailpit SMTP
```

Reglas:

- `postgres` no se conecta a `edge/test`.
- `e2e-runner` no se conecta a `backend`.
- no se dependerá de la red `default` implícita de Compose para servicios protegidos;
- CI no publica PostgreSQL al host;
- CI no configura `host.docker.internal`, `network_mode: host` ni `extra_hosts` que permitan puentear el aislamiento;
- API/control-plane sólo publican puertos al host en perfiles de debug/smoke donde sea útil; el journey E2E usa DNS interno (`http://api:8000`, `http://control-plane:8001`);
- Mailpit HTTP puede estar en edge únicamente para assertions de plumbing; SMTP permanece backend;
- Vault no se expone al runner salvo que un contrato público del sistema lo requiera, que hoy no debe ocurrir.

CI debe tener una **prueba negativa del boundary** antes del journey:

1. desde `e2e-runner`, `postgres` no resuelve o no es alcanzable en 5432;
2. el entorno del runner no contiene variables `*_DATABASE_URL`, `PG*` ni migration DSNs;
3. `import request_engine` no está disponible como aplicación instalada;
4. no existe `/var/run/docker.sock`;
5. `docker inspect` desde el orquestador confirma que el runner sólo está en `edge/test`.

Un test que sólo “promete” no usar DB no satisface este requisito.

## 4. Bootstrap, migrations y provisioning inicial

F-01 no puede eliminar la ceremonia inicial privilegiada: un deployment vacío necesita migrations, roles runtime y trust root antes de que exista una API autenticable.

### Setup de infraestructura permitido

- `alembic upgrade head`;
- creación de logins/roles runtime;
- `request-engine-platform-bootstrap issue`;
- `request-engine-platform-bootstrap establish`.

Estas acciones son one-shot, usan la misma imagen de Request Engine y pueden acceder a backend/PostgreSQL porque forman parte de la instalación del sistema.

Objetivo de Compose: representar `migrate` y `bootstrap` como servicios one-shot explícitos o invocaciones equivalentes con límites de credenciales estrechos. No es requisito semántico que exista un nombre de servicio `bootstrap`; sí lo es que la ceremonia use la misma imagen, credenciales de instalación separadas y no mezcle estado de negocio.

### Estado de negocio prohibido por SQL

Después del trust root, todo lo siguiente debe nacer mediante contratos soportados:

- segundo operador de seguridad;
- platform provisioner;
- organización/tenant;
- tenant controller;
- staff;
- AGENT/INTEGRATION/workload principal;
- supply/capacity;
- booking;
- revocación;
- recovery;
- sustitución de controladores/autoridad.

No se acepta un fixture SQL para que el journey “llegue” a un estado conveniente.

## 5. Handoff seguro de credenciales y estado entre fases

El nuevo diseño ejecuta varias invocaciones efímeras de `e2e-runner`, por lo que debe definir explícitamente cómo sobreviven estado y credenciales.

### 5.1 Secretos

- GitHub/orquestador genera las credenciales de bootstrap/controlador necesarias.
- Todo secreto dinámico se enmascara inmediatamente con `::add-mask::` antes de cualquier echo accidental.
- El bootstrap token se usa sólo para `establish` y **no** se entrega al `e2e-runner`.
- Passwords/proofs/tokens reutilizables se pasan mediante Docker/Compose secrets o archivos efímeros con permisos restrictivos montados sólo en el runner/proceso que corresponda.
- No se pasan secretos en argv, URLs, `docker compose config` materializado, labels ni nombres de contenedor.
- El directorio/volumen de secretos está fuera de `.ci/docker-e2e/`, nunca se sube como artifact y se destruye al finalizar.

### 5.2 Estado del journey

Entre fases se necesita conservar IDs/revisiones/checkpoints sin volver al DB. Se permite un volumen efímero dedicado `e2e-state` montado **sólo** en `e2e-runner`.

- `state.json` conserva IDs/revisiones y datos no sensibles necesarios para continuar.
- Si una credencial one-time debe sobrevivir entre fases, va en un namespace/archivo separado del volumen con permisos 0600, nunca en `checkpoints.json` ni artifacts.
- Siempre que sea posible, una fase posterior vuelve a autenticar por API en vez de persistir bearer tokens.
- El volumen se destruye con `docker compose down -v`.
- `checkpoints.json` para artifacts se genera a partir de una vista sanitizada, no copiando el estado crudo.

No se permite usar una tabla auxiliar de PostgreSQL como state bus del test.

## 6. Mapeo trazable del F-01 normativo

Esta tabla evita que el plan Docker reduzca accidentalmente el F-01 original.

| Contrato F-01 | Checkpoint/lane Docker | Oracle mínimo |
| --- | --- | --- |
| 1. Instancia limpia native-only; migrations y bootstrap CLI, sin inserts de Principal/grants | F01-01 | login del platform controller funciona; no seed SQL de negocio |
| 2. Segundo operador de seguridad, provisioner, organización y tenant controller | F01-02 / F01-03 | cada autoridad nace por ceremonia/API soportada y queda autenticable |
| 3. Staff + AGENT/INTEGRATION con techos/policy explícitos | F01-04 / F01-05 | actor y ceilings/policy observables; no autoelevación |
| 4. Supply de citas por API + onboarding listo para ese journey | F01-06 / F01-07 | supply creado y `/v1/onboarding/readiness` refleja readiness del journey, no readiness ficticio |
| 5. Agente descubre operación/schema, agenda con actor propio; forged tenant/party/capability rechazado | F01-08 / F01-09 | booking válido existe; ataque no crea reserva **ni outbox extra**; discovery usa operation/schema real |
| 6. Revocación local; token todavía criptográficamente válido deja de operar inmediatamente en ese tenant | F01-10 | siguiente uso falla sin afectar tenants/autoridad no objetivo |
| 7. Recovery completo: request→approve→stage→issue→deliver adapter→consume HTTP; old password/session fallan; grants no reviven; respuesta perdida se reconcilia | F01-11 | login nuevo reconcilia outcome; secreto no aparece en logs/state público; grants siguen revocados |
| 8. Retirar último controlador falla; crear sustituto y repetir según revisión; provenance preservada | F01-12 | primer command recibe conflicto accionable; segundo éxito mantiene continuidad/provenance |
| 9. Native→OIDC: dual proof, misma autoridad de negocio, disable native y fallback correcto | lane separada F01-OIDC | Authentik/profile opt-in; no reconstruir Principal/grants; native-only sigue independiente |
| 10. Crash/restart worker **y API** en puntos de saga; estado y secreto siguen seguros | F01-13→F01-17 | recuperación durable, idempotencia/no duplicación, secretos no reviven/filtran |

### Checkpoints propuestos

```text
F01-01 clean bootstrap + platform login
F01-02 second security operator + platform provisioner
F01-03 organization + tenant controller
F01-04 tenant login + authority observation
F01-05 staff + AGENT/INTEGRATION identity/policy ceilings
F01-06 supply/capacity provisioning
F01-07 onboarding readiness for appointment journey
F01-08 operation/schema discovery + valid booking
F01-09 adversarial forged tenant/party/capability; no booking/outbox side effect
F01-10 local revocation + immediate denial with previously valid token
F01-11 governed recovery + delivery + consume + lost-response reconciliation
F01-12 last-controller refusal + replacement + successful retry + provenance
F01-13 prepare durable worker/API saga state
F01-14 worker crash/restart
F01-15 verify worker durable recovery/idempotency
F01-16 API crash/restart at selected saga point
F01-17 verify API/client reconciliation and secret/state safety
F01-OIDC separate opt-in Native→OIDC migration/disable journey
```

Cada checkpoint debe emitir:

- nombre estable;
- start/end timestamp;
- PASS/FAIL;
- IDs/revisiones no sensibles útiles para diagnóstico;
- `correlation_id`/request-id cuando exista;
- duración;
- mensaje de error sanitizado;
- oracle/side-effect negativo relevante cuando aplique.

El summary del run debe poder indicar exactamente dónde murió el journey.

## 7. Fault injection: worker y API

`e2e-runner` **no recibe `/var/run/docker.sock`**.

La inyección de fallo pertenece al orquestador GitHub/Compose.

### Worker

```text
1. e2e-runner crea trabajo durable por API
2. e2e-runner persiste checkpoint sanitizado
3. GitHub/Compose mata worker en el punto seleccionado
4. GitHub/Compose reinicia worker
5. e2e-runner vuelve a autenticar y verifica resultado/recovery
```

### API

```text
1. e2e-runner inicia una operación/saga con outcome observable
2. GitHub/Compose detiene/mata API en el punto de prueba soportado
3. GitHub/Compose reinicia API y espera readiness
4. e2e-runner reconcilia mediante receipt/read/login según el contrato
5. se comprueba no duplicación, no pérdida silenciosa y no filtración/revivificación de secretos
```

No se aceptan `sleep` arbitrarios como único mecanismo para acertar una race. Cuando haga falta coordinar el punto de fallo se usará una condición observable, barrier/test hook explícitamente acotado o evento durable del sistema que no cambie la semántica bajo prueba.

No se arrancará un worker falso con `WORKER_PRINCIPAL_ID` inventado o publisher dummy sólo para producir verde. El principal y las capacidades del worker deben provenir de provisioning soportado en el journey o de una ceremonia runtime explícitamente documentada.

## 8. Compose de referencia objetivo

Servicios:

```text
postgres             PostgreSQL 18
migrate              one-shot, misma imagen Request Engine
bootstrap (*)        one-shot/invocación, misma imagen Request Engine
vault                dev mode sólo para plumbing
mailpit               SMTP catcher + API de inspección
api                   misma imagen Request Engine
control-plane         misma imagen Request Engine
worker                misma imagen Request Engine, profile/arranque controlado
e2e-runner            imagen mínima de pruebas black-box
[authentik]           job/profile separado para Native→OIDC
```

`(*)` puede ser servicio Compose o `docker compose run` equivalente; la propiedad requerida es el boundary, no el nombre.

`depends_on`/healthchecks se usan para dependencias técnicas, pero readiness del sistema se valida explícitamente. `migrate`/bootstrap deben terminar exitosamente antes de runtime; los servicios runtime deben alcanzar health/readiness real.

Las credenciales se distribuyen por **need-to-know**. No se usa un único `x-common-env` que entregue indiscriminadamente DSNs de app/worker/platform-read/platform-control a todos los procesos. Cada superficie recibe sólo su login/DSN y secretos necesarios.

## 9. Estrategia de pruebas por nivel

No todo debe ir a este Compose.

```text
unit tests
    pytest in-process

integration tests pequeños
    pytest + dependencias efímeras/Testcontainers cuando aporten valor

system/E2E F-01
    Docker Compose + e2e-runner black-box
```

Testcontainers es apropiado para componentes/adapters que necesitan una dependencia real aislada. No sustituye al Compose F-01 porque aquí la unidad bajo prueba es una **topología completa** con varios procesos, bootstrap, worker/API lifecycle y fault injection.

## 10. GitHub Actions objetivo

Esqueleto conceptual:

```yaml
- checkout
- build request-engine:<sha> once
- build e2e-runner minimal image
- create ephemeral secret/state material outside artifact tree
- docker compose up postgres vault mailpit
- run migrate one-shot
- run bootstrap one-shot
- docker compose up api control-plane
- wait readiness
- assert e2e-runner isolation negatively
- docker compose run --rm e2e-runner <F01-01..12>
- provision/start worker when its real identity exists
- docker compose run --rm e2e-runner <F01-13 prepare>
- orchestrator kill/restart worker
- docker compose run --rm e2e-runner <F01-15 verify>
- orchestrator kill/restart API at selected point
- docker compose run --rm e2e-runner <F01-17 reconcile/verify>
- collect sanitized evidence always
- upload artifact always
- teardown -v + destroy ephemeral secrets always
```

El workflow actual de host-smoke se conserva como capa de deployment mientras P3 migra el journey al runner aislado. Cuando el black-box runner esté estable, se decidirá si el host-smoke queda como job pequeño separado o se integra sin duplicación inútil.

## 11. Evidencia y observabilidad obligatorias

Un failure debe permitir contestar **qué falló, en qué checkpoint, en qué servicio, con qué correlación y qué pasó inmediatamente antes/después**.

Artefacto objetivo:

```text
.ci/docker-e2e/
├── summary.md
├── metadata.json
├── junit.xml
├── checkpoints.json             # sanitizado
├── isolation-proof.json
├── request-engine-image.json
├── EVIDENCE_SCOPE.txt
├── phases/
│   ├── build.log
│   ├── infrastructure.log
│   ├── migrate.log
│   ├── bootstrap.log
│   ├── readiness.log
│   ├── isolation.log
│   ├── journey.log
│   ├── worker-recovery.log
│   └── api-recovery.log
├── services/
│   ├── postgres.log
│   ├── api.log
│   ├── control-plane.log
│   ├── worker.log
│   ├── vault.log
│   └── mailpit.log
└── docker/
    ├── compose-ps.txt
    ├── compose-config.sanitized.txt
    └── inspect.sanitized.json
```

Propiedades:

- recolección `if: always()` y best-effort;
- logs con timestamps;
- logs por servicio, no sólo un `compose.log` gigante;
- metadata del SHA/run/attempt;
- JUnit del runner;
- checkpoint summary;
- prueba de aislamiento del runner;
- redacción de tokens/passwords/Authorization headers/recovery material/signing keys/DSNs;
- retention limitada;
- GitHub Step Summary compacto con PASS/FAIL por fase/checkpoint;
- evidencia de exit/restart counts del worker/API alrededor de fault injection.

### Regla de secreto para artifacts

No se sube `docker compose config` o `docker inspect` crudo si contienen environment/secret material. Se genera una proyección sanitizada o se remueven campos sensibles antes del artifact. Un regex posterior es defensa en profundidad, no el control primario.

El collector debe minimizar secretos **antes** de persistir evidencia. Si en el futuro entran credenciales dinámicas reales de CI, la suite debe fallar cerrada si el sanitizador no puede garantizar la proyección esperada.

## 12. Qué prueba y qué NO prueba

### Evidencia válida en CI

- imagen única reproducible de Request Engine;
- migrations + bootstrap desde cero;
- least-privilege/need-to-know de credenciales por superficie en el deployment de referencia;
- readiness de superficies runtime;
- HTTP/TCP real desde otro contenedor;
- aislamiento negativo del test runner respecto a DB/internals;
- provisioning sin SQL fixtures;
- journeys multi-actor/authority;
- onboarding del journey;
- operation/schema discovery por agente;
- booking/capacity y ataques sin side effects extra;
- revocación local inmediata;
- recovery gobernado y reconciliación;
- continuidad/last-controller;
- worker y API crash/restart con recuperación observable;
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

## 13. Estado real del branch y gaps conocidos

Esta sección existe para evitar que la arquitectura objetivo se confunda con implementación ya terminada.

### Ya demostrado en el smoke base

- una imagen `request-engine:<sha>` sirve a migrate/API/control-plane y resuelve worker al mismo artifact;
- PostgreSQL 18 corre separado;
- migrations + runtime logins + bootstrap CLI arrancan un mundo limpio;
- API/control-plane alcanzan readiness real;
- TCP smoke desde host funciona;
- logs/metadata/inspect se recogen como artifacts;
- el check sigue experimental (`continue-on-error`) durante calibración.

Un cambio documental posterior crea un HEAD nuevo; por tanto la frase “smoke base verde” describe evidencia previa del comportamiento, no sustituye exact-head CI del commit final.

### Pendiente / debe corregirse durante P2-hardening/P3a

1. `e2e-runner` todavía no existe.
2. Compose todavía no separa `edge`/`backend`; usa la red implícita.
3. PostgreSQL/API/control-plane aún publican puertos al host para el smoke actual.
4. `x-common-env` actual distribuye más DSNs/credenciales de las necesarias a varias superficies; debe dividirse por proceso.
5. El worker todavía tiene placeholders/defaults para principal/publisher y no constituye evidencia P4.
6. El bootstrap se ejecuta actualmente con `docker compose run api ...`; puede mantenerse sólo si se estrecha su entorno, o convertirse en servicio one-shot dedicado.
7. El collector actual persiste `docker compose config`/`docker inspect` antes de una sanitización suficientemente estructural; debe producir proyecciones sanitizadas antes de introducir secretos dinámicos al runner.
8. No existen aún `junit.xml`, `checkpoints.json` ni `isolation-proof.json` del F-01 containerized.
9. Fault injection de API exigida por F-01 todavía no está implementada.
10. Native→OIDC completo sigue siendo lane separada pendiente; la cobertura existente de dual-proof no sustituye el journey completo.

Ninguno de esos puntos debe ocultarse marcando P3/P4 como completos.

## 14. Fases revisadas

| Fase | Estado / entregable |
| --- | --- |
| P0 | Decisión de alcance/gating: completada; check experimental durante calibración |
| P1 | Imagen única RE + PostgreSQL separado + compose + migrate/runtime roles: baseline implementado |
| P2a | Docker host-smoke + readiness + evidencia básica: implementado y demostrado |
| P2b | Hardening de evidencia: sanitización estructural, env/secret minimization, exact-head summaries |
| P3a | `e2e-runner` mínimo + `edge/backend` + secret/state handoff + pruebas negativas de aislamiento |
| P3b | F01-01→F01-12 black-box, incluido onboarding/discovery/side-effect oracles |
| P4 | Worker real + F01-13→15 + API F01-16→17 crash/restart/reconciliation |
| P5 | Vault dev + Mailpit: stage/publish/reconcile y assertions de plumbing |
| P6 | Subconjunto G + lane F01-OIDC/Authentik separado cuando corresponda |
| P7 | Calibrar flakiness, retirar `continue-on-error`, promover a required check |

P2b y P3a pueden avanzar juntos porque la introducción del runner obliga a endurecer el manejo de secretos/evidencia.

## 15. Definition of Done

P3/P4 no están terminados hasta que se pueda demostrar todo lo siguiente en exact-head CI:

1. un único artefacto de Request Engine sirve migrate/bootstrap/API/control-plane/worker;
2. PostgreSQL corre separado;
3. `e2e-runner` corre en su propio contenedor mínimo;
4. el Dockerfile/imagen del runner no instala `request_engine` como aplicación ni copia internals innecesarios;
5. el runner no tiene DB DSN, acceso de red a PostgreSQL, host networking, host gateway ni Docker socket;
6. existe una prueba negativa automatizada de esos boundaries y queda en `isolation-proof.json`;
7. el estado de negocio de F-01 se crea por CLI inicial + APIs soportadas, no fixtures SQL;
8. el F-01 normativo 1→10 está mapeado y cubierto, incluida readiness, discovery/schema, forged actor inputs sin side effects, recovery completo, last-controller, OIDC lane y crash/restart worker+API;
9. F01-01→17 reportan checkpoints claros y F01-OIDC tiene su lane explícita;
10. worker crash/restart demuestra recuperación durable/idempotente real;
11. API crash/restart demuestra reconciliación correcta del cliente/saga, sin duplicación ni pérdida silenciosa;
12. JUnit, logs, inspect sanitizado, metadata y summaries sobreviven incluso a failure;
13. secretos/material sensible no aparecen en artifacts ni compose/inspect crudos;
14. credenciales runtime se distribuyen por need-to-know, no mediante un env común indiscriminado;
15. un desarrollador puede reproducir localmente el mismo journey con Compose sin conocer una DSN de DB;
16. el check ha sido calibrado suficientemente antes de hacerlo requerido;
17. `EVIDENCE_SCOPE.txt` deja explícito qué propiedades continúan fuera de CI.

## 16. Criterios de falsificación

El plan debe considerarse roto —aunque CI esté verde— si ocurre cualquiera de estas condiciones:

- un test importa un service/repository interno para crear/verificar el outcome principal;
- el runner puede abrir conexión a PostgreSQL;
- un ID/revision necesario se obtiene por SELECT porque falta una lectura pública;
- el worker arranca con principal/publisher inventado sólo para pasar;
- el ataque adversarial recibe rechazo pero deja reserva/outbox/side effect residual;
- recovery se “prueba” llamando directamente al service interno o leyendo el proof desde DB;
- un crash/restart se sustituye por recrear un mundo nuevo;
- un `sleep` es el único coordinador de una race;
- un artifact contiene token/password/recovery proof/DSN/signing key sin redactar;
- una fase marcada PASS no tiene oracle observable independiente;
- se llama “production-ready” a evidencia de Vault dev/Mailpit.

## 17. Evaluación honesta del cambio de plan

Este diseño es **mejor que el plan original para F-01** porque reduce falsos positivos causados por un harness demasiado privilegiado y obliga a que los gaps públicos aparezcan como fallos reales. El plan anterior sigue siendo útil como smoke de deployment y por eso se conserva esa capa, pero no es la frontera adecuada para certificar un customer/system journey.

El nuevo `e2e-runner` introduce trabajo adicional: imagen de test, redes explícitas, state/secret handoff, checkpoints, sanitización estructural y coordinación de worker/API fault injection. Ese trabajo compra propiedades útiles: aislamiento verificable, reproducibilidad y una prueba mucho más cercana a cómo un consumidor externo realmente usa Request Engine.

La regla rectora queda así:

> **Si F-01 necesita acceso a PostgreSQL o a internals para poder pasar, F-01 ha encontrado un gap del producto o del deployment. El test no debe esconderlo.**
