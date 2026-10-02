# Admin production hardening — 2026-10-02

## Reporte simple (para humanos)

Esta continuación añade un historial administrativo de cada miembro, corrige una
comprobación que podía declarar disponible el panel con su API de usuarios caída
y verifica que las pruebas temporales del almacén de secretos tengan vencimiento
real. El historial no concede acceso adicional ni revela datos privados.

No es una certificación de producción. Chrome no está disponible en la conexión
de herramientas. Faltan la aceptación de correo real y del entorno de despliegue,
la política operativa de destrucción y backups de secretos, y las métricas de
identidad cuyo contrato aún requiere definición. No se borraron datos del usuario.

## Reporte técnico (detallado)

### Cambios de sistema

- Tenancy: GET `/v1/staff/members/{membership_id}/history`, operationId
  `staff_history_list`, HUMAN `staff.read` vigente, Query sin idempotencia ni
  mutaciones. Target/cursor/autoridad comparten snapshot SQL con RLS tenant.
  Orden `(created_at,id) DESC`, `limit+1`, cursor solo del mismo miembro/tenant.
  Proyección cerrada de cuatro comandos, sin payload/provenance/contactos.
  DTO, aplicación y adaptador permanecen separados. No nueva migración.
- BFF: `routes_tenant_staff.py` y `templates/resources/staff_history.html`;
  página separada, solo API runtime, credencial de sesión y selector tenant,
  errores sanitizados, navegación newest/older y enlace desde el detalle.
  El diseño mantiene la consulta fuera de los formularios de mutación y evita
  inventar actividad de login o entrega de invitaciones.
- `app.py`: readiness comprueba `/health/ready` de control y runtime configurados;
  liveness no llama dependencias. Fallos upstream devuelven 503 genérico sin
  datos del proveedor. No verifica directamente DB ni almacenes secretos.
- `settings.py`: URLs HTTP(S) sin credenciales/query/fragmento/puertos inválidos;
  SameSite=None requiere Secure. HTTP local/SameSite=Lax sigue permitido.
- Adaptadores Vault/OpenBao: metadata TTL antes de CAS0 y verificación de
  `deletion_time` de la versión efectiva, incluyendo ganador de CAS. Fail closed
  sin DELETE ambiguo. Nuevo helper técnico `kv_v2_retention.py` y probe opt-in.
  ACL del proveedor debe permitir metadata create/update en namespace temporal.
- Pruebas: matriz pública/aislamiento clasifica history; runner PostgreSQL actual
  incluye `tests/db/test_staff_membership_history.py`. Pruebas BFF ejercitan
  autenticación, autorización/errores, forwarding y ausencia de payload privado.

### Evidencia y límites

- Antes de estos cambios, los nueve checks remotos del SHA
  `388adf5cfda65da06f463a7fcee58ac685895137` aprobaron. Esa evidencia no certifica
  el nuevo working tree ni el despliegue de producción.
- Prueba aislada Vault 1.21.0, puerto 58200: versión inicial con TTL efectivo,
  replay CAS conserva ganador y data GET devuelve 404 después de caducidad.
  Reporta `physical_destruction_proven: false`. Contenedor de prueba eliminado.
  No equivale a prueba real de OpenBao. 120 pruebas focales de stores/assembly
  aprobaron; Ruff y Pyright focales aprobaron.
- Chrome: inventario solo IAB/MCP Apps; `createBrowserTab("chrome",...)` devuelve
  `Browser is not available: chrome`. No recorrido visual/WebAuthn certificado.
- Windows/uv, working tree final: `uv run python scripts/ci/ci_jobs.py python-quality`
  terminó con exit 0; lint, formato, Pyright, scan de secretos, análisis de
  seguridad, auditoría de dependencias, arquitectura, unit y módulos PASS.
  Dos intentos previos detectaron errores del nuevo test BFF: primero formato,
  luego un assertion demasiado amplio que incluía formularios globales. Se
  corrigió el alcance al contenido de la página; la corrida final pasó.
- `uv run pytest tests/unit/admin_console/test_tenant_staff.py -q --tb=short`:
  26 passed, incluyendo seis respuestas de historial y forwarding/redacción.
- PostgreSQL 18 aislado `127.0.0.1:55433/request_engine_admin_verify`:
  `uv run pytest tests/db/test_staff_membership_history.py -q -m postgres --tb=short`:
  4 passed. Comandos reales producen el audit; replay no duplica eventos;
  prueba independiente de empate temporal y UUID, cursor ajeno y revocación.
- Mismo PG: `uv run pytest tests/e2e/test_native_identity_recovery_http.py -q
  -m postgres -k 'test_identity_recovery_delivery or
  test_identity_recovery_ambiguous_delivery_is_not_blindly_retried or
  test_identity_recovery_connection_failure_is_safely_retried' --tb=short`:
  3 passed, 5 deselected.
- Mismo PG: `uv run pytest tests/e2e/test_http_security_matrix.py
  tests/e2e/test_http_tenant_isolation_matrix.py -q -m postgres -k staff --tb=short`:
  17 passed, 102 deselected; incluye historial. `uv run pytest
  tests/e2e/test_public_surface_contract.py -q -m postgres --tb=short`: 4 passed.
  Son pruebas focales, no el runner PostgreSQL completo.
- Docker local puerto 5432: PostgreSQL 18.6 y `alembic_version` =
  `0011_staff_member_profiles`, igual al head vigente. El launcher local
  `run_local_panel.ps1 -ControlPort 8011 -ConsolePort 8012 -RuntimePort 8010`
  terminó correctamente; control/runtime readiness 200; consola readiness
  devuelve ready y OpenAPI runtime publica `staff_history_list`.
  No certifica una sesión de navegador autenticada ni un despliegue productivo.

### Revisión semántica del autor

Contexto: diff de esta continuación, reader y pruebas completos, rutas BFF y
plantillas, contrato Tenancy history, adaptadores KV-v2 y helper, protocolo SRP-1.
El scan de working tree contra origin/development emitió 104 candidatos en todo
el branch; no son 104 defectos de esta continuación ni evidencia exact-head.

- History reader (QR-FSIZE): HEALTHY_AS_IS, confianza alta. Snapshot único mantiene
  autorización/target/cursor juntos; extraer los CTE por LOC ocultaría la frontera.
  Contraargumento: SQL creciente requiere medir volumen antes de aceptar más
  proyecciones. Prueba requerida: RLS/autoridad/cursor/no efectos, ejecutada.
- Tests history y transporte (QR-FSIZE): HEALTHY_AS_IS, confianza alta. Casos
  independientes falsifican defectos distintos; no fragmentar para bajar LOC.
- Rutas staff BFF (QR-FSIZE/QR-CPLX): REVIEW_CONCERN, confianza media. Conviven
  varias páginas relacionadas y ramas de autenticación/errores; nueva history
  no añade mutaciones ni autoridad. Revisar responsabilidad de rutas si crece;
  no crear un proxy genérico ni un camino SQL alternativo. Prueba requerida:
  lint/types/arquitectura y BFF ejecutadas.
- Retention helper: HEALTHY_AS_IS, confianza alta. Abstracción técnica real de
  dos proveedores, no extracción ceremonial; staging/CAS permanecen locales en
  cada adaptador. Contraargumento: versiones/API proveedor distintas requieren
  aceptación real por proveedor, OpenBao real pendiente.

No human_verdict ni aprobación humana inferida. Estos juicios no sustituyen
pruebas deterministas ni autorizan excepciones a garantías.

### Pendientes concretos, sin falsos equivalentes

1. Destrucción física: no existe janitor certificado. Diseñar limpieza por
   namespace cerrado, versiones explícitas y gracia, con reconciliación de
   resultados ambiguos y pruebas de competencia. Soft-delete no es destrucción.
   Retención de snapshots/backups requiere política y aceptación operativa.
2. SMTP real: ejecutar la aceptación existente contra el proveedor/destino
   productivo con secretos protegidos, verificar recepción y reintentos. Mailpit
   y CI no certifican una bandeja externa.
3. Despliegue: aceptar TLS/ingress, cookies, ACL de secretos, backups/restauración,
   alertas y readiness contra el entorno productivo elegido; no se proporcionó
   un destino productivo verificable. Simulaciones P7 no sustituyen esa aceptación.
4. Journey Chrome/passkeys: repetir alta/invitación/preview/accept/tenants/permisos,
   denegaciones y recuperación en Chrome conectado. No guardar secretos reales
   en fixtures ni sustituir Chrome con una prueba ASGI.
5. Perfil/telemetría: definir propiedad y privacidad de contacto confirmado,
   último acceso, sesiones y directorio entre organizaciones. Display name tenant
   y self `my-organizations` no representan esas métricas. No conceder acceso
   global implícito al administrador de plataforma.
6. Publicación: certificado pre-push del SHA final, CI exact-head y revisión antes
   de merge en development; main permanece release-only.

No baseline ni garantías HARD modificadas. No reset ni migración destructiva.
