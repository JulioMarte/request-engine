# Revisión personal de cierre — 2026-10-06

## Reporte simple (para humanos)

Estado: revisión en curso; producción no certificada. Se revisa el trabajo
actual personalmente, sin subagentes. Las pruebas se ejecutan en instalaciones
desechables; no se borraron datos ni se reemplazó el historial de migraciones.

La revisión de calidad pasó. La instalación inicial y la actualización completa
en una base vacía también pasaron, incluyendo una segunda base en el mismo
servidor. Las baterías funcionales completas aún deben terminar.

GitHub tiene una prueba de inventario de rutas fallida; otro trabajo depende de
esa prueba y por eso también figura fallido. Hay una corrección local de ese
inventario, todavía no certificada por GitHub. Además aparecieron modificaciones
durante la revisión: no se presenta el árbol local como un commit inmutable.

La base de la aplicación local está atrasada respecto al código. No fue
actualizada ni reiniciada en esta revisión. Una instalación de pruebas verde
no sustituye actualizar y aceptar el entorno que realmente se desplegará.

Hay además una descripción confusa en la consulta de revisión de permisos:
habla de quitar permisos actuales, aunque comprueba permisos previamente
revocados. No se observó que esto permitiera saltarse la autorización, pero un
cliente puede interpretar mal la respuesta. Sigue pendiente corregir el contrato.
Tampoco están certificados aquí correo real, infraestructura, recuperación ante
desastres ni capacidad bajo carga. La revisión formal de mantenibilidad requiere
evidencia del código final, no los paquetes antiguos disponibles.

## Reporte técnico (detallado)

### Alcance y procedencia

- Branch: `feature/admin-console`; HEAD observado:
  `72b2d38fd62558a6754c64e0f9cdb0299616d830`.
- `git ls-remote origin refs/heads/development` confirmó
  `1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`, igual al merge base local.
- Había cambios locales antes de empezar. Durante la revisión aparecieron cambios
  adicionales en `tests/e2e/http_surface_contract_support.py` y
  `tests/e2e/http_surface_controller_policy.py` que no realizó este revisor.
- No commit, push, merge, cambio de permisos, DDL productivo ni despliegue.
- Se pidió aclarar «rebaseline»: validación limpia frente a sustitución de historia.
  Sin esa aclaración se conserva `0001_initial` y su payload inmutable. Probar
  el baseline no equivale a generar otro baseline.

### Evidencia ejecutada

Windows, Python 3.13.1, Docker PostgreSQL 18.6. Artefactos:
`.ci/final-review-20261006/`.

1. `uv run python scripts/ci/ci_jobs.py python-quality --log-dir
   .ci/final-review-20261006/quality --summary-output
   .ci/final-review-20261006/quality/summary.json`: **12/12 PASS**, exit 0.
   Arquitectura 203, unitarias 1079, módulos 752. Una advertencia de deprecación
   Starlette/httpx; no error. No confundir con la ejecución del 5 de octubre,
   que había fallado Pyright y había omitido los pasos posteriores.
2. `bash scripts/ci/run_current_product.sh`, con `PG*`, URL de migración y
   `CURRENT_PRODUCT_CI_ARTIFACT_DIR` apuntando exclusivamente al nuevo contenedor
   `request-engine-personal-review-20261006`, base `request_engine_review`.
   Primer intento: instaló hasta `0033_adopt_fact_tenant_rls` y salió por ausencia
   de `psql` en PATH. Segundo intento usa el cliente PostgreSQL portable del
   workspace. Baseline independiente y multibase: **PASS**. Runner completo:
   **EN CURSO**, no aprobado todavía.
3. `bash scripts/ci/run_e2e_platform.sh all`, con namespace
   `personal-review-20261006` y artefactos `docker-e2e/`: **EN CURSO**.
   Cada suite crea un mundo independiente. La imagen del motor es
   `sha256:7882fdef139ec5ee77a9e8dc9a68a085bcd726df783eacc5f1ddfaceaf672aeb`.
   Docker prueba Linux y fronteras TCP; no prueba infraestructura productiva.
4. Consulta de solo lectura a `request-engine-postgres-1`:
   `request_engine_current`, PostgreSQL 18.6, revisión
   `0025_agent_credential_rotation`. No se aplicó 0026–0033 allí.
5. `gh pr checks --json name,state,link` y `gh run view 37507400648
   --job ... --log-failed`: PR #137, mismo HEAD, current-product **FAIL** por
   inventario HTTP sin las tres rutas tenant de adopción. La lane V3 depende
   de ese resultado y falla su prerrequisito, no una segunda prueba de producto.
   Los cambios locales del inventario no son evidencia remota exact-head.

### Hallazgo contractual pendiente

La nueva proyección local `capability_delta_is_non_revoking` en
`tenancy/api/controller_policy_adoption_routes.py` se calcula como
`not row.revoked_capabilities`, pero su descripción y ADR 0016 dicen que indica
si el delta elimina grants actuales. No es lo que calcula el SQL:
`0027_controller_policy_adoption.py::review_controller_policy_adoption` retorna
capabilities del target con un grant revocado y sin un grant activo. Es un bloqueo
por posible restauración de autoridad previamente revocada, no una eliminación
de permisos existentes. La autoridad de apply no se ha observado debilitada por
esto; el defecto es de interpretación del contrato para clientes/agentes.
Debe corregirse de forma coordinada con quien está editando esa superficie,
sin interpretar el booleano como autorización para aplicar.

### Límites que siguen siendo gates de salida

- Finalizar y revisar los runners completos, sin sumar ejecuciones parciales
  como si fueran una única aprobación.
- Estabilizar el árbol; repetir evidencia afectada si cambia el código y ejecutar
  CI sobre el commit final. Los sensores de mantenibilidad no son aprobación humana.
- Actualización y aceptación de la aplicación local/productiva, separadas de la
  instalación de pruebas. No reconstruir ni borrar la base para esconder el atraso.
- Aceptación de TLS/ingress, SMTP/proveedor real, permisos del gestor de secretos,
  operación del worker, backup/restore con fence, alertas y límites bajo carga.
  Mailpit y proveedores locales no acreditan estas propiedades productivas.

### Mantenibilidad: alcance de la revisión

El scan local marcó tres `QR-FSIZE-001`: pruebas de apply/apply (331 líneas
efectivas), apply/withdraw (436) y apply/revocación de owner (393). No son
fallos de arquitectura y no se dividieron para reducir una métrica. El paquete
disponible `QR-7ce31b8ba060` identifica source/tested SHA `12e55a54`, no el HEAD
actual ni sus cambios sin commit. Disposición formal: `INSUFFICIENT_CONTEXT`,
confianza alta en la discrepancia de procedencia; `human_verdict: null`.
Hace falta generar paquetes del candidato final antes de cerrar la revisión.
La inspección de las carreras muestra conexiones independientes y observación
de `pg_blocking_pids`; eso no reemplaza ejecutarlas ni prueba todas las carreras
posibles contra suspensión, recuperación o cambios de grants.
