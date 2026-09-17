# Plan de e2e real en Docker dentro de GitHub CI

Fecha: 2026-09-17. Branch de referencia: `cohesion/system-optimization`. HEAD de
referencia: `b8d9eacc`, revisión vigente `0055_authority_inspect_policy`.

Estado: **plan de ejecución propuesto, no certificación ni autorización de
despliegue**. El objetivo es ejecutar en GitHub Actions los journeys
end-to-end que hoy faltan (F-01 y el subconjunto CI-feasible de G), levantando el
stack real en contenedores Docker y capturando logs, porque el producto se
desplegará realmente en Docker. Complementa
`architecture/auth-production-completion-plan.md` (§11 y §12) y
`architecture/sequential-completion-plan.md`.

## 0. Verdad incómoda antes de empezar

1. **No se puede "solo añadir un job".** Hoy no existen **Dockerfiles** para
   API/control-plane/worker ni un **compose de referencia** de la app. El único
   compose es PostgreSQL (`compose.yaml`); `deploy/authentik` y
   `deploy/observability` son stacks aparte. Para testear "como se desplegará de
   verdad" hay que **construir primero el artefacto de despliegue** (entregable
   G1/G2 del plan §12).
2. **El harness e2e actual es ASGI in-process** (`httpx.ASGITransport`), no TCP
   real. F-01 exige TCP real contra contenedores. Hay que escribir un journey
   **nuevo**, no reutilizar los e2e actuales.
3. **F-01 exige "sin fixtures"**: hoy el mundo se siembra por SQL/definer
   (`native_provisioning_support.py`). El journey debe arrancar por **ceremonia
   CLI + provisioning HTTP**.
4. **Vault dev + SMTP de prueba (MailHog/Mailu) prueban el cableado, no la entrega
   real.** El plan §12 dice literalmente *"fake provider no certifica delivery"*.
   El resultado debe etiquetarse como **evidencia de plumbing**, no certificación
   de producción.
5. **NO son certificables en CI**: TLS/ingress verificado desde fuera,
   deliverability real de correo, backup/restore production-shaped +
   restore-fencing, break-glass humano, RPO/RTO/SLO. Eso queda para D6/entorno
   real.
6. **El job será lento y propenso a flakes** (build + 6-7 contenedores + migración
   + journey). Recomendación: empezar **no-bloqueante** y promoverlo a requerido
   tras calibrar.

## 1. Qué testear

| Objetivo | CI-feasible en Docker | No CI-feasible (D6) |
| --- | --- | --- |
| **F-01** pasos 1-8 y 10 (bootstrap CLI, provisioner, org, tenant, staff/agent/integration, supply, booking, revoke, recovery por adapter de test, último controlador, crash/restart worker) | Sí | — |
| **F-01** paso 9 (Native→OIDC con disable) | Sí pero pesado (Authentik); job separado opt-in | — |
| **G** 1 (entrypoints/pools), 2 (readiness), 4 parcial (límites), 8 providerless/adapter, 9 (OpenAPI) | Sí | — |
| **G** 3 TLS/ingress externo, 5 delivery real, 6/7 backup/restore production-shaped, 8 break-glass humano | No | Sí |

## 2. Mecanismo de GitHub Actions (con docs)

Docs consultadas: *About service containers*, *Running jobs in a container*, y la
referencia `jobs.<job_id>.services` / `jobs.<job_id>.container`.

**Decisión: `docker compose` sobre el runner `ubuntu-24.04`, NO un container job.**

- Un *container job* (`jobs.<job_id>.container`) ejecuta **un** contenedor; además
  `--network` y `--entrypoint` no están soportados. Nuestra app son **varias**
  superficies (API + control plane + worker + PostgreSQL + Vault + SMTP). No
  encaja.
- Los *service containers* (`jobs.<job_id>.services`) sirven para sidecars y **ya
  se usan** para PostgreSQL. Pero para levantar la app real conviene
  `docker compose`, que es exactamente el artefacto de despliegue que queremos
  validar.
- Los runners `ubuntu-24.04` de GitHub traen Docker + Compose v2, y **no** tienen
  rate limit de Docker Hub. Los contenedores requieren runner Linux (cumplido).

Servicios del stack e2e (compose de referencia):

```text
postgres:18        (healthcheck pg_isready)      -> ya es el estándar del repo
migrate (one-shot) (alembic upgrade head)         -> depends_on postgres healthy
vault              (dev mode, root token)         -> KV v2 para el secret store
mailhog | mailu    (SMTP catcher + API HTTP)      -> verifica envío real del correo
api                (uvicorn create_app)           -> /health/live, /health/ready
control-plane      (platform_server)              -> 3 logins: db/read/control
worker             (request-engine-worker)        -> REQUEST_ENGINE_WORKER_FACTORY
[authentik]        (job separado, opt-in)         -> OIDC
```

- Comunicación: en compose todos comparten red por nombre de servicio; los tests
  corren en el **runner** contra `localhost:<puerto>` mapeado.
- `depends_on: condition: service_healthy` / `service_completed_successfully` para
  ordenar.
- **Logs**: `docker compose logs --no-color --timestamps` por servicio a
  `.ci/docker-e2e/logs/`, más `docker inspect`/exit codes, subidos con
  `actions/upload-artifact@v4` en un step `if: always()` (captura también en
  fallo).

## 3. Activos a crear (fase previa, imprescindible)

1. **Dockerfiles**: `deploy/reference/api.Dockerfile`, `control-plane.Dockerfile`,
   `worker.Dockerfile` (base `python:3.13-slim` + `uv`; sin secretos en la imagen).
2. **Compose de referencia**: `deploy/reference/compose.e2e.yaml`, con healthchecks
   y sin credenciales de producción.
3. **Migración on-start**: servicio `migrate` one-shot con `MIGRATION_DATABASE_URL`.
4. **Provisioning de roles**: script que cree los logins runtime
   (app/worker/read/control) y la migración; hoy los tests crean roles efímeros
   ad hoc.
5. **Wait-for-readiness**: script que espere `/health/ready` con timeout y vuelque
   logs si falla.
6. **Journey F-01**: test nuevo en `tests/e2e_docker/` que hable HTTP/TCP real y
   arranque por CLI bootstrap (sin SQL).

## 4. Fases

| Fase | Entregable | Depende de |
| --- | --- | --- |
| P0 | Decisión de alcance y gating (bloqueante vs experimental) | owner |
| P1 | Dockerfiles + compose de referencia + migrate + roles + healthchecks | — |
| P2 | Job `docker-e2e` en CI: levanta stack, espera readiness, recoge logs | P1 |
| P3 | Journey **F-01** fixture-free sobre TCP real | P2 |
| P4 | Crash/restart de worker + verificación de secretos/logs | P3 |
| P5 | Vault dev + MailHog: verificar stage/publish/reconcile real del correo | P3 |
| P6 | Subconjunto G: readiness, pools separados, OpenAPI; opcional Authentik | P2-P5 |
| P7 | Promover a check requerido tras calibrar flakes | P2-P6 |

## 5. Esqueleto del workflow

```yaml
name: docker-e2e
on:
  pull_request: { branches: [development] }
  workflow_dispatch:
concurrency:
  group: docker-e2e-${{ github.ref }}
  cancel-in-progress: true
jobs:
  docker-native-journey:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v6
      - name: Build stack
        run: docker compose -f deploy/reference/compose.e2e.yaml build
      - name: Start stack
        run: docker compose -f deploy/reference/compose.e2e.yaml up -d
      - name: Wait for readiness
        run: bash scripts/ci/wait_for_stack.sh
      - name: Bootstrap ceremony (CLI)
        run: docker compose -f deploy/reference/compose.e2e.yaml exec -T control-plane \
             request-engine-platform-bootstrap
      - name: F-01 native fixture-free journey
        run: uv run pytest tests/e2e_docker -q -m docker_e2e
      - name: Collect container logs
        if: always()
        run: bash scripts/ci/collect_stack_logs.sh .ci/docker-e2e/logs
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: docker-e2e-logs
          path: .ci/docker-e2e/
      - name: Tear down
        if: always()
        run: docker compose -f deploy/reference/compose.e2e.yaml down -v
```

## 6. Evidencia y logs

- Artefacto `docker-e2e-logs`: logs por servicio + `docker inspect` + exit codes +
  salida de pytest (JUnit XML).
- Marcar explícitamente en el artefacto: **"plumbing evidence (Vault dev + SMTP
  catcher); not production delivery certification"**.
- Correlación: `correlation_id` de las respuestas HTTP con los logs del worker.

## 7. Límites honestos (repetidos a propósito)

- Vault **dev** no prueba producción (sellado, HA, políticas reales).
- MailHog/Mailu **captura** correo; no prueba entrega real, SPF/DKIM/reputación.
- TLS/ingress, backup/restore con restore-fencing, RPO/RTO y break-glass **quedan
  fuera**; son G/D6 en entorno real.
- El job es caro: recomendación de **no-bloqueante** al inicio.

## 8. Riesgos y decisiones abiertas

1. **Gating**: ¿bloqueante desde el inicio o experimental? (recomendación:
   experimental, luego requerido tras calibrar).
2. **Fidelidad vs coste**: ¿Vault dev + MailHog (rápido) o Vault prod-mode + Mailu
   real (lento)?
3. **OIDC**: ¿incluir Authentik en CI (job aparte) o dejar el paso 9 para entorno
   real?
4. **Restore-fencing**: la herramienta no existe; ¿bloque propio (G) o fuera de CI?
5. **Imágenes**: ¿build en CI cada vez o publicar a GHCR con cache?

## 9. Criterios de éxito

- `docker compose up` levanta API + control plane + worker + PostgreSQL + Vault +
  SMTP y todos llegan a `healthy/ready`.
- El journey F-01 completa bootstrap→booking→revoke→recovery→último
  controlador→crash/restart contra los contenedores reales.
- Los logs de todos los servicios quedan como artefacto descargable, incluso en
  fallo.
- CI exact-head verde y reproducible; el artefacto declara sus límites.
