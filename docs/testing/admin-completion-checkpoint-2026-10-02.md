# Admin implementation checkpoint — 2026-10-02

## Reporte simple (para humanos)

El panel permite reconocer miembros por un nombre local, buscar ese nombre y
filtrar por estado. Cambiar el nombre no cambia la cuenta ni sus permisos.
El destinatario de una invitación puede revisar la organización y el vencimiento
antes de aceptar; aceptar sigue sin conceder permisos administrativos.

Los contadores nuevos muestran actividad real de configuración del proceso actual,
no estadísticas inventadas de usuarios o de las últimas 24 horas. No se borraron
datos: la base del panel se actualizó y los tres servicios arrancaron correctamente.

Esto es un cierre parcial, no la entrega completa de las imágenes. Falta comprobar
el recorrido real en Chrome y correo, la eliminación física de secretos temporales
y ofrecer un historial autorizado de cambios de permisos. Contactos, sesiones,
último acceso y consultar todas las organizaciones de otra persona no quedan
autorizados ni implementados por una etiqueta local.

## Reporte técnico (detallado)

### Cambios de producto y fronteras

- Tenancy: `PATCH /v1/staff/members/{membership_id}/profile`, operationId
  `staff_profile_update`, capability HUMAN `staff.manage_membership`. Nombre nullable,
  revisión independiente, idempotencia obligatoria y autoridad actual validada bajo
  bloqueo incluso en replay. Ver [contrato de perfiles](../architecture/staff-member-profiles.md).
- `0011_staff_member_profiles`: tabla tenant-local, FK compuesto, FORCE RLS,
  SELECT limitado a cuatro columnas para la aplicación, sin DML directo; dos
  primitivas de comando con owner/search_path/EXECUTE explícitos. Sin backfill,
  cambios a baseline ni revisiones ya publicadas. Downgrade perdería etiquetas.
- `staff_list` aplica filtros de estado y substring literal Unicode antes del
  límite. `%` y `_` no son comodines. Los contadores siguen cubriendo el tenant
  completo, no el subconjunto filtrado.
- `POST /v1/staff/invitations/{invitation_id}:preview`, operationId
  `staff_invitation_preview`: native HUMAN bearer y prueba secreta, sin selector
  tenant ni mutación. La aceptación revalida todo. El BFF no consulta la base ni
  adquiere autoridad por el nombre mostrado.
- Panel: `routes_tenant_staff.py`, plantillas staff, `forms.py`/`inputs.py` admiten
  el PATCH canónico y borrado explícito mediante null; campos opcionales vacíos
  siguen omitidos. Paginación conserva filtros; cambiar filtros empieza desde raíz.
  El listado utiliza todo el ancho; vinculación por UUID queda en un disclosure
  avanzado, separado de la invitación por correo como recorrido principal.
- `routes_staff_invitations.py` y `static/invitation.js`: CSRF, respuesta mínima,
  render de nombre con `textContent`, aceptación desactivada hasta preview válido
  y protección contra restaurar un enlace olvidado mientras llega su preview.
- `routes_operations.py`/dashboard: cuatro contadores de configuración de la API
  existente; ausencia, fallo, booleanos y negativos no se convierten en cero.
  CSS añade tarjetas/estados y disposición adaptable sin simular métricas.

### Evidencia ejecutada y entorno

Pruebas PostgreSQL usan **18.6**, `127.0.0.1:55433/request_engine_admin_verify`,
separada de los datos del panel. No interpretar fixtures destructivas como permiso
para ejecutarlas contra la base interactiva.

- `uv run python scripts/ci/ci_jobs.py python-quality --summary-output
  .ci/admin-completion-final-python-quality-20261002.json --log-dir
  .ci/admin-completion-final-python-quality-20261002`: PASS, código 0; incluye
  lint/formato/tipos, seguridad, **201 architecture**, **733 unit** y **633 modules**.
  Una expectativa posterior del test revoked se corrigió de conflicto de revisión
  a conflicto de estado (SQLSTATE 55000); publicación necesita certificación del
  commit exacto, no atribuirle este resultado de working tree.
- Perfiles + privilegios/roles/runtime: **25 passed**, 215.66 s;
  `.ci/admin-profile-pg-20261002.xml`. Incluye dos conexiones compitiendo bajo un
  bloqueo observado, ganador único, perdedor stale y auditoría única.
- Contrato HTTP y matriz foreign para perfil: **4 passed, 68 deselected**,
  46.88 s; `.ci/admin-profile-http-pg-20261002.xml`. La prueba de clasificación
  completa debe admitir PATCH con idempotencia obligatoria, no omitirlo del registro.
- Node: `node --test tests/unit/admin_console/invitation_script.test.cjs`:
  **3 passed**. Es ejecución del script real con DOM/fetch de prueba, no navegador,
  WebAuthn, correo ni prueba incorporada al runner canónico.
- Suite focal del panel + HTTP profile/invitaciones: **136 passed**; después del
  disclosure avanzado, `test_tenant_staff.py`: **20 passed**.
- Base interactiva Docker PostgreSQL `request_engine_current:5432`:
  `uv run alembic upgrade head` aplicó 0010 → **0011_staff_member_profiles**;
  consulta posterior verificó esa revisión. No reset ni eliminación.
- `scripts/dev/run_local_panel.ps1 -ControlPort 8011 -ConsolePort 8012
  -RuntimePort 8010`: tres readiness **200** tras reinicio. `/login` devolvió 200;
  OpenAPI runtime expone `staff_profile_update`. Esto no prueba sesión autenticada.
- Suite ampliada `test_public_surface_contract`, lifecycle staff, email invitations,
  schema/runtime privileges F1 e index cohesion: **65 passed**, 571.36 s;
  `.ci/admin-staff-schema-pg-20261002.xml`.
- Perfiles finales, incluyendo revocación real seguida de edición/replay rechazados
  sin auditoría ni idempotencia extra: **6 passed**, 56.92 s;
  `.ci/admin-profiles-final-pg-20261002.xml`. La primera ejecución falló por esperar
  el subtipo equivocado; no hubo cambio de comportamiento para hacerla pasar.
- `uv run python scripts/db/prove_multidatabase_migration_compatibility.py`: PASS;
  segunda base temporal instalada desde baseline hasta 0011 con roles compartidos
  auditados y eliminada por el propio script al terminar.

Chrome primero figuraba en inventario pero no podía seleccionarse; al volver a
consultar solo aparecen IAB y MCP Apps. No se sustituyó Chrome, no hubo capturas
ni prueba visual autenticada y no se usó Bitwarden. No se certificó envío real a
un buzón ni limpieza física por proveedor. CI remoto del nuevo cambio está pendiente.
No se ejecutó el runner completo `run_current_product.sh` ni Docker E2E: las suites
anteriores son evidencia focal real y no sustituyen esas lanes.

### Próxima implementación, sin caminos paralelos

1. Consulta Tenancy de historial administrativo: owner, capability de lectura,
   privacidad, paginación estable y DTO mínimo deben quedar explícitos antes del
   endpoint. Usar auditoría durable existente, no duplicar hechos ni leerla desde
   el panel. Mostrar actor/revisión/transición con provenance redactada. Pruebas:
   dos cambios y revocación reales, replay sin duplicados, foreign 404, autoridad
   revocada 403 y ausencia de mutaciones. La pregunta normativa pendiente es
   «quién creó/cambió/revocó esta autoridad», del plan actual de provisioning.
2. Evidencia operativa de secretos: validar TTL físico de versiones y huérfanos;
   fallo de metadata debe ser observable. Expiry lógico no prueba destrucción.
   No borrar candidatos por generación tras fallo: podría ser el ganador concurrente.
3. Chrome/correo reales: invite → login/enrollment → preview → accept con cero
   grants → nombre → plan/apply → acción permitida y denegada → suspensión.
   Registrar revisión, proveedor real y sustituciones. Suspensión conserva el
   alcance global de revocación de sesiones nativas; no prometer aislamiento por tenant.
4. Proyecciones de contacto/sesiones/persona→tenants requieren autoridad de
   privacidad explícita. `my-organizations` es self-only; platform owner no adquiere
   implícitamente permisos tenant. No construir un directorio por joins privados.

### Revisión semántica del cambio

Revisión del autor, no aprobación humana ni excepción a invariantes. Contexto:
diff, contratos Tenancy/perfiles/invitaciones, BFF/forms, SQL 0011, pruebas reales,
playbook y protocolo. El scan de trabajo contra `origin/development` encontró
97 candidatos en **todo el branch**, no 97 defectos nuevos; no es un paquete de
evidencia exact-head ni una prueba de completitud.

- `0011` QR-NAV: HEALTHY_AS_IS. `upgrade`/`downgrade` son fronteras Alembic reales,
  no forwarding ceremonial; mantener SQL de tabla/ACL/primitivas en la revisión.
- Readers, comandos, DTOs, forms y pruebas QR-FSIZE: HEALTHY_AS_IS para esta
  ampliación. Responsabilidades locales y límites explícitos; no extraer para bajar LOC.
- Rutas BFF staff/invitaciones QR-FSIZE/QR-CPLX: REVIEW_CONCERN. Las ramas de
  autenticación, catálogo, CSRF, errores y flujo son necesarias, pero repetición
  preview/accept y tamaño acumulado merecen revisión posterior por responsabilidad.
  No introducir helper genérico que pueda reenviar tenant al flujo pre-membership.
- `routes_operations.py`: HEALTHY_AS_IS para contadores; una proyección sobre
  respuesta ya leída, sin nueva autoridad, provider I/O ni modelo estadístico.
- Matriz HTTP: HEALTHY_AS_IS. Clasificar PATCH evoluciona el método soportado;
  idempotencia, metadata, ausencia de efectos y aislamiento siguen obligatorios.

No nuevas dependencias entre módulos ni flexibilización de límites HARD. Después
de cualquier cambio de código se requiere repetir pruebas deterministas pertinentes.
