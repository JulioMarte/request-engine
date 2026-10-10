# Evaluación adversarial y coherencia del API — 2026-10-03

## Reporte simple (para humanos)

**La evaluación no está completa y el API aún no permite administrar todo lo
modelado sin retener información privada en el cliente.** Configurar el panel
no significa que todos los recorridos de administración estén terminados.

Tres revisiones independientes encontraron fallos de reintento, validación,
documentación y continuidad de los recorridos. Algunas áreas permiten crear
información, pero no recuperarla al reconectar. También hay una contradicción
entre cómo el catálogo cuenta recursos y cómo las reservas consumen capacidad.

No se demostró un acceso indebido entre organizaciones en esta pasada. Tampoco
se demostró que todos los endpoints lo rechacen correctamente. Las pruebas
seleccionadas pasaron, incluidas siete pruebas reales de permisos en una base
separada. La configuración del usuario no se borró ni se utilizó para pruebas.

Esta pasada deja diagnóstico y un plan verificable; no corrige producción.
Primero deben cerrarse los fallos reproducibles. Después deben completarse las
lecturas administrativas y demostrar recorridos desde un cliente sin memoria.
Una interfaz más bonita no sustituye esas operaciones del API.

## Reporte técnico (detallado)

### Estado, procedencia y alcance

Informe no normativo sobre el worktree de `feature/admin-console`, base local
`e4f65b59eae4fcc032f3b7effc0550c165fe6ee7` con cambios previos pendientes.
No equivale a certificación de ese commit ni del código final de una futura PR.
El OpenAPI procede de procesos locales ya iniciados: puede no reflejar cada
cambio pendiente del disco. Las reproducciones ASGI usan el código del worktree.

Informes subordinados, con fuentes exactas y reproducciones:

- [Autoridad e identidades](api-authority-audit-2026-10-03.md): A1–A5.
- [Contrato HTTP y autenticación](api-http-security-contract-audit-2026-10-03.md): H-01–H-03.
- [Recorridos de negocio](api-business-journey-audit-2026-10-03.md): BJ-001–BJ-007.

Esta pasada cambió esos documentos, este informe y el índice `docs/README.md`.
No cambió funciones de producción, APIs, autorización, migraciones ni políticas.
Los cambios anteriores del worktree se preservaron; no son implementación nueva
de esta auditoría. No hubo commit, push, merge ni aceptación de CI remoto.

### Inventario observado, no cobertura comportamental

| Proceso | Slots método/path | Con capability | Capability sin security efectivo en OpenAPI | Capability sin 401 documentado |
|---|---:|---:|---:|---:|
| Runtime localhost:8010 | 204 | 175 | 175 | 169 |
| Control localhost:8011 | 78 | 46 | 6 | 3 |

Son 282 slots HTTP, no necesariamente 282 operaciones de negocio diferentes.
No convertir este conteo en porcentaje de cobertura. Un esquema completo no
demuestra ejecución segura; metadata ausente no demuestra bypass. La consulta
consideró tanto `operation.security` como seguridad global del documento.

### Bloqueos y orden de resolución

| Orden | Hallazgo | Evidencia actual | Corrección y condición de cierre |
|---|---|---|---|
| 1 | A1: provisioning de identidad promete idempotencia, pero acepta POST sin clave ni recibo | ASGI 201, una llamada al servicio; contrato required | Command owner, recibo durable, autoridad actual transaccional; PG: replay, conflicto, carreras y retirada de autoridad |
| 1 | BJ-001: entradas inválidas devuelven 500 | Dos reproducciones ASGI, cero llamadas a persistencia | Error de entrada específico/validación DTO; blancos, duplicados y combinaciones inválidas deben dar error contractual sin efectos |
| 1 | BJ-002: count de recursos sustituye unidades por recurso | Contradicción estática en catálogo y Booking, dos contraejemplos | Predicado estructural coherente; PG con un units-capacity2 y dos exclusive1, múltiples requisitos; Booking conserva validación final |
| 1 | H-03: cuentas con varias passkeys y desconocidas tienen distinta cardinalidad | Servicio real y Fido2: 2 frente a 1 | Política uniforme acotada que mantenga acceso con cada llave, incluida compatibilidad no discoverable; HTTP/PG y privacidad |
| 2 | H-01/H-02: autenticación mal descrita, errores/challenge incompletos | OpenAPI live y dos GET anónimos 401 sin challenge | Proyectar autenticación real por composición; públicos explícitos; probar esquema y rechazo real, sin reemplazar resolver |
| 2 | A2/BJ-003: faltan reads de owner, supply y políticas | Routers/catálogo inspeccionados; comandos requieren revisiones | Queries autorizadas tipadas, revisión actual, no secretos; reconstrucción tras descartar todas las respuestas del cliente |
| 2 | BJ-004: definición/versiones y bandeja de Requests no administrables | Superficie existente requiere definiciones previas | Contrato de versiones/activación y bandeja del owner; tenant vacío configurable sin SQL ni endpoint especial del panel |
| 3 | A3/A5/BJ-005/BJ-006: filtros silenciosos, continuación falsa, resultados opacos y colecciones incompletas | Repros ASGI, OpenAPI y lectura estática | Query DTO cerrado, límites/continuación veraz, DTOs de salida; más de una página y terminal exacta |
| Investigar | A1 autoridad durante provisioning; BJ-007 replay tras cambio de definición | Hipótesis estática, no carrera reproducida | Reproducción PG determinista antes de afirmar vulnerabilidad o rediseñar semántica |

No corregir H-03 truncando arbitrariamente a una llave. No capturar globalmente
todos los `ValueError` para esconder BJ-001. No rebajar la metadata idempotente
para aparentar que A1 está cerrado. No bloquear reemplazo de passkey en recovery:
W-03 describe un recorrido aceptado, no un exploit demostrado.

### Qué significa administrar todo lo modelado

No significa exponer todas las tablas. Por cada concepto aceptado del producto,
el owner debe declarar: quién puede descubrirlo, leer su estado/configuración,
obtener revisión, ejecutar las transiciones permitidas y reconstruir el resultado
después de pérdida de respuesta. Si una operación no debe ser pública, declarar
su frontera interna y el mecanismo operacional soportado, no inventar CRUD.

Recorrido mínimo de aceptación:

1. Crear/configurar usando solo operaciones soportadas y autenticación real.
2. Descartar IDs y revisiones retenidos por el cliente; iniciar un cliente nuevo.
3. Descubrir organización y relaciones autorizadas, sin confiar en selector tenant.
4. Recuperar IDs, estado y revisiones mediante Queries owner-backed.
5. Planificar/cambiar permisos con revisión actual y comandos semánticos.
6. Repetir comandos tras respuesta perdida; comprobar un efecto y recibo estable.
7. Retirar autoridad o cambiar revisión desde otra conexión; el cliente anterior
   debe recibir rechazo útil sin efectos secundarios indebidos.
8. Proyectar ese mismo recorrido en panel y herramientas, sin escritura paralela.

El catálogo de operaciones ayuda a descubrir acciones. No sustituye la lectura
de recursos ni concede autoridad sobre ellos.

### Matriz obligatoria antes de afirmar evaluación completa

Esta matriz es un criterio de cierre, **no una afirmación de pruebas realizadas**.
Cruzar el inventario montado con garantías y evidencia ejecutada. No usar la
presencia de un archivo de test ni el nombre de un operationId como oracle.

| Riesgo por operación aplicable | Casos mínimos | Frontera requerida |
|---|---|---|
| Autenticación/aislamiento | Anónimo, sesión caducada/revocada, tenant ajeno, ID ajeno/inexistente, filtros falsificados | HTTP real + owner; PG restricted roles para aislamiento |
| Autoridad | Capability insuficiente, relación Party incorrecta, withdrawal, último controller, recovery restringido | Owner real; conexiones PG independientes en carreras |
| Entrada/contrato | Campos extra, blancos, límites, enums, combinaciones incompatibles, IDs/cursores inválidos | HTTP/DTO y owner; error útil y ausencia de efectos |
| Idempotencia | Falta clave, retry idéntico, conflicto, concurrentes, pérdida de respuesta, retirada de autoridad | Recibo/transacción real PG, no doble de persistencia |
| Revisión/estado | Obsoleta, transición prohibida, simultáneas, loser sin efectos, resultado recuperable | PG y journey HTTP |
| Lecturas | Página siguiente/última, filtros, orden, sensibilidad, no-store, reconexión | Reader real + HTTP; no historial ilimitado |
| Proveedores/worker | Timeout, resultado ambiguo, retry/fencing, reconciliación, terminal delivery, expiry/destrucción | Integración real aislada y fault injection |
| Capacidad/tiempo | Recursos units/exclusive, superposición, DST, cancel/reschedule/queue/service invariantes | PG y operaciones reales; oracle independiente |
| Herramientas | Discoverability distinta de autorización, misma owner operación, args no crean identidad confiable | Discovery + ejecución real |

Marcar cada celda `EJECUTADO`, `ESTÁTICO`, `PENDIENTE` o `NO_APLICA` con motivo.
Vincular `INV-*`, test concreto, defecto que lo hace fallar, entorno, revisión,
comando y resultado. Priorizar operations por riesgo, no por cantidad de rutas.
`current-proof-map.toml` es representativo: no es una cobertura exhaustiva.

### Evidencia nueva ejecutada

- Agente autoridad: ocho archivos unit/module seleccionados, **81 passed / 11.45s**.
- Agente HTTP/security: tres archivos unit seleccionados, **36 passed / 4.26s**.
- Agente negocio: cuatro archivos module seleccionados, **35 passed / 1.63s**.
- Reproducciones ASGI sin DB y servicio WebAuthn: consultar informes subordinados.
- Root volvió a ejecutar las reproducciones documentadas de A1 y BJ-001/BJ-005:
  POST sin clave: 201/una llamada; blanco y requisito duplicado: 500/cero llamadas;
  schema de éxito sin propiedades. Los contraejemplos quedaron corroborados
  independientemente, sin persistencia ni conexión a la base del usuario.
- Root: GET OpenAPI de ambos procesos, conteos anteriores corroborados.
- Root: PostgreSQL **18.6**, base dedicada `request_engine_admin_verify`,
  host 127.0.0.1, puerto **55433**, Alembic `0013_temporary_proof_inventory`.
  Verificados por `current_database()`, `inet_server_port()`, `version()` y
  consulta de `public.alembic_version` antes de ejecutar pruebas.

Comando PostgreSQL ejecutado en PowerShell, variables explícitas para evitar
los defaults de fixtures que truncan datos:

```powershell
$env:PGHOST='127.0.0.1'
$env:PGPORT='55433'
$env:PGDATABASE='request_engine_admin_verify'
$env:PGUSER='request_engine'
$env:PGPASSWORD='request_engine' # Credencial exclusivamente del entorno de prueba
uv run pytest tests/db/test_staff_replay_authority.py tests/db/test_staff_invitation_anchor_authority.py -q -p no:cacheprovider
```

Resultado: **7 passed in 61.67s**. Protege autoridad actual de recibos staff e
invitaciones; no protege todos los endpoints de provisioning ni arregla A1.
Los fixtures limpian esa base dedicada. No se ejecutaron tests sobre la base
del usuario en puerto 5432.

Validación general de Python ejecutada:

```powershell
uv run python scripts/ci/ci_jobs.py python-quality --log-dir .ci/api-coherence-audit-quality --summary-output .ci/api-coherence-audit-quality.json
```

Resultado: exit 0, **12 pasos PASS**, incluyendo Ruff, Pyright, escáneres,
dependencias, **201 pruebas de arquitectura, 974 unit y 656 module**.
Unit emitió una advertencia; su lane terminó PASS. Registro completo en
`.ci/api-coherence-audit-quality.json`. `uv run alembic heads` confirmó una única
head: `0013_temporary_proof_inventory`. El código de producción no cambió durante
esta auditoría; los documentos finales se terminaron después de los checks.
No sustituye la lane PostgreSQL actual, clean-install Docker E2E ni evidencia
exact-head de GitHub. Los contraejemplos anteriores muestran límites concretos
del conjunto actual de pruebas aunque esta lane esté verde.

### Decisiones, límites y trabajo pendiente

- Decidido: conservar ownership, garantías y recovery de reemplazo vigente;
  no introducir caminos únicos del panel ni modificar datos del usuario.
- Pendiente: política de privacidad multi-passkey; contrato administrativo de
  provisioning; reads de owner/supply; lifecycle de definiciones Requests.
- Pendiente: pruebas PG de los nuevos contraejemplos, cobertura endpoint/riesgo
  completa, `run_current_product.sh`, Docker E2E desde cero, SMTP/infraestructura
  productiva, performance y aceptación de navegador.
- Auditoría no equivale a autorización para publicar o integrar el worktree
  heterogéneo. Publicación requiere lane y certificación local; merge requiere
  evidencia exact-head remota sobre el cambio coherente.

### Referencias externas consultadas

[OWASP API Security Top 10 2023](https://api-security.owasp.org/editions/2023/en/0x11-t10/)
informa la revisión de autenticación, autoridad sobre objetos/funciones,
consumo de recursos e inventario. No constituye una certificación del sistema.
[Google AIP-158](https://google.aip.dev/158) orienta la continuidad y el contrato
de paginación. Su nomenclatura no sustituye el estándar propio de Request Engine.
