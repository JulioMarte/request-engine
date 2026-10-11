# Aceptación manual del panel — 2026-10-03

## Reporte simple (para humanos)

Esta guía prueba recorridos reales, no solamente que las pantallas abran. El
entorno es local y de desarrollo. Pasar esta lista no certifica producción.
Los casos sin proveedor, trabajador o recorrido de interfaz disponible se marcan
**BLOQUEADO**, nunca **PASS**. La preparación y las comprobaciones ejecutadas se
registran al final; los casos manuales siguen pendientes hasta que los pruebes.

Abre **http://localhost:8012/setup en Chrome**. Usa `localhost`, no `127.0.0.1`.
No compartas contraseñas, enlaces completos de invitación, códigos de recuperación,
cookies, archivos HAR sin limpiar ni capturas que contengan esos datos.

## Reporte técnico (detallado)

### Preparación y cuentas

- Panel: `http://localhost:8012`; control plane: puerto8011; API tenant: puerto8010.
- PostgreSQL18 local: puerto5432, base `request_engine_current`, inicialmente
  `unclaimed`, sin Principals ni Organizations tras el reset autorizado.
- El panel consume las APIs reales. No utiliza el mock ni escribe SQL de negocio.
- Crea una cuenta `owner.manual@example.invalid`, contraseña exclusiva de prueba,
  passkey real y guarda los códigos de recuperación fuera del repositorio.
- Prepara dos contextos de navegador separados: perfil Chrome normal para el
  administrador e incógnito/otro perfil para el invitado. No supongas que una
  passkey estará disponible en incógnito: eso depende del autenticador.
- Para correo local usa direcciones ficticias capturadas por el entorno de prueba;
  para correo productivo, exclusivamente un buzón real controlado por ti.
- Crea organizaciones **Manual A** (`manual-a`) y **Manual B** (`manual-b`). Para
  el primer recorrido puedes usar tu propia identidad como controller de ambas.
  Copia su `native_identity_id` del recibo del setup o de Native identities.
  Esto es asignación explícita: ser Platform Owner no da acceso automático al tenant.
- Conserva solamente IDs no secretos: identidades, organizaciones, membresías,
  invitaciones y revisiones. Usa referencias como `manual:2026-10-03:caso-P01`.
- Antes de suspender, revocar o recuperar cuentas, asegúrate de tener otra sesión
  administrativa utilizable y los códigos offline. Nunca pruebes revocaciones
  irreversibles sobre tu única cuenta de acceso.

### Orden recomendado y resultado esperado

Marca cada fila **PASS / FAIL / BLOQUEADO / NO PROBADO**. Un rechazo esperado
cuenta como PASS sólo si tampoco cambió el estado que debía protegerse.

| ID | Qué hacer | Qué verificar |
| --- | --- | --- |
| S01 | Iniciar setup, elegir usuario y contraseña. | Pasos claros; no se crea un administrador efectivo antes de finalizar. |
| S02 | Cancelar el diálogo de passkey y luego repetirlo. | Cancelar no finaliza setup ni muestra un éxito falso; puedes reintentar. |
| S03 | Registrar passkey real y generar códigos. | Chrome/autenticador acepta el alta; códigos visibles una vez, guardados privadamente. |
| S04 | Finalizar y abrir `/setup` en otra pestaña. | Instance claimed; setup permanece cerrado; no aparece una segunda creación de owner. |
| A01 | Salir y entrar con passkey, sin escribir usuario. | Acceso real y navegación disponible; no basta que Chrome acepte la selección. |
| A02 | Entrar con contraseña incorrecta/usuario inexistente. | Error comprensible, sin revelar cuál usuario existe; ninguna sesión autorizada. |
| A03 | Entrar con contraseña y ejecutar un cambio que exige passkey. | Se pide prueba adicional; cancelar no cambia nada; completar reintenta la intención original. |
| A04 | Cerrar sesión; usar Atrás, recargar y abrir URL privada directamente. | No recuperas acceso autenticado; una imagen antigua en caché no demuestra autorización. |
| A05 | Abrir sesión en otro perfil; probar expiración/revocación al final. | La siguiente consulta/comando vuelve a validar acceso; no confíes sólo en botones visibles. |
| O01 | Organizations → Create organization, Manual A y Manual B. | Recibos con IDs correctos; cada organización aparece una vez. |
| O02 | My organizations → abrir A y B. | Sólo aparecen organizaciones con vínculo autorizado; el tenant activo se distingue claramente. |
| O03 | Entrar con una identidad nativa sin membership. | No obtiene acceso tenant sólo por poder iniciar sesión. |
| O04 | Con un miembro sólo de A, abrir una URL de B y un recurso de B. | Denegación/ausencia sin nombres, permisos ni historial de B. No debe bastar cambiar el ID en la URL. |
| U01 | Native identities → Provision identity de prueba. | Identidad creada, contraseña no reaparece; todavía no tiene membership/grants implícitos. |
| U02 | Vincular identidad existente con Invite/add existing identity en A. | Una membership, identidad correcta y ningún permiso automático. Es distinto de invitar por correo. |
| U03 | Cambiar nombre visible del miembro en A; consultar B si pertenece también. | Nombre local al tenant; no cambia login ni permisos ni el perfil de B. |
| U04 | Buscar por nombre, filtrar estados y limpiar filtros. | Resultados coherentes; tabla vacía no se confunde con servicio caído. |
| U05 | Abrir detalle e historial del miembro. | Tenant, estado y revisiones correctos; historial consistente con acciones realmente realizadas. |
| U06 | Con más filas que el límite, ir a siguiente/anterior. | Sin filas repetidas/perdidas en un conjunto quieto; filtros preservados. Con pocas filas marca NO PROBADO. |
| P01 | Seleccionar permisos, explicar motivo y Preview changes. | Muestra altas/bajas exactas; preview no concede permisos. |
| P02 | Aplicar el preview y refrescar; probar como el usuario afectado. | Estado/API y acceso efectivo coinciden; no basta una notificación verde. |
| P03 | Intentar conceder permisos fuera del alcance delegable del administrador. | Denegación; no se borran ni amplían otros permisos por accidente. |
| P04 | Quitar un permiso y repetir una acción con la sesión del afectado. | La siguiente llamada lo rechaza sin exigir logout voluntario del usuario. |
| P05 | Dos pestañas editan desde la misma revisión. | Primer cambio válido; segundo conflicto visible, obliga a refrescar; no sobrescribe silenciosamente. |
| P06 | Reenviar la misma intención/doble clic. | No duplica membership, concesión ni evento de negocio. Si no puedes reproducir la misma intención, no lo declares probado. |
| M01 | Suspender una cuenta descartable, probar acceso y reactivar. | Suspensión quita acceso; reactivación no revive automáticamente sesiones revocadas. |
| M02 | Suspender miembro presente en dos tenants. | Advertencia visible: se revocan sus sesiones nativas globalmente. Membership de B no debe cambiar por la acción sobre A. |
| M03 | Intentar retirar el último controller autenticable. | Rechazo y continuidad de administración. No pruebes una operación irreversible sobre el único owner sin alternativa. |
| I01 | Invitaciones por correo → crear invitación. | Historial separa estado de invitación y entrega; queued no dice que llegó al buzón. |
| I02 | Abrir correo y enlace en el perfil del destinatario. | Organización/expiración correctas; autenticación y confirmación previas a aceptación. |
| I03 | Si no tiene cuenta, completar alta por invitación; luego aceptar. | Se crea/vincula la identidad correcta y una membership sin permisos. |
| I04 | Aceptar de nuevo el mismo enlace. | No crea una segunda membership; resultado coherente con consumo/idempotencia. |
| I05 | Reenviar otra invitación y abrir el enlace anterior. | Enlace viejo inválido; el nuevo es utilizable. |
| I06 | Revocar una invitación pendiente y abrirla. | No permite aceptar; un correo ya enviado puede seguir en el buzón sin que su enlace sea válido. |
| I07 | Probar enlace caducado, alterado o correspondiente a otro tenant. | Rechazo seguro, sin conceder membership ni filtrar recursos extranjeros. No cambies el reloj del sistema. |
| I08 | Inspeccionar fallo temporal/permanente de entrega en entorno controlado. | No hay éxito falso, secretos ni stack traces; indicación de reintento/intervención coherente. No envíes ráfagas para forzar throttling. |
| R01 | Recuperación offline sobre cuenta de prueba con factor y código conservados. | Contraseña anterior inválida, código de un uso, acceso restringido hasta completar recuperación; setup sigue cerrado. |
| R02 | Completar recuperación con factor fuerte por la API soportada. | Se recupera autoridad sólo tras ceremonia válida; un simple refresh no basta. Si no hay recorrido UI, marca BLOQUEADO EN PANEL. |
| R03 | Recovery cases: creación, revisión, aprobación por otro humano e issuance. | Doble control real, revisiones, estado/entrega; autoaprobación indebida rechazada. Requiere segundo operador provisionado. |
| C01 | Configuration: draft → validate → provider test → activate. | Draft no es Active; errores de configuración no activan una revisión inválida. |
| C02 | Secrets: crear, lookup por binding ID, rotar y revocar secreto de prueba. | Nunca se vuelve a mostrar plaintext; metadatos/revisión correctos. No se promete enumeración de secretos. |
| C03 | Deployment recovery: inspect/compare/preview/reconcile. | No escribe sin configuración/proveedor/revisiones válidas; requiere entorno de proveedor dedicado, no producción por accidente. |
| D01 | Overview, Workspaces y Diagnostics. | Estados reales y enlaces funcionales; datos ausentes no aparecen como números inventados o salud garantizada. |
| D02 | All operations: búsqueda y formularios. | Endpoint/capability/inputs comprensibles; error útil; operación no queda inaccesible por falta de workspace. |
| V01 | Comparar con las nueve imágenes originales. | Jerarquía visual, sidebar, tablas legibles, estados y acciones claras; documenta diferencias, no presupongas equivalencia pixel-perfect. |
| V02 | Ventana estrecha y zoom200%; usar Tab/Shift+Tab/Enter/Escape. | Sin controles cortados; foco visible; menú/dialog accesibles; cancelar no ejecuta acciones. |
| V03 | Operación lenta, error, doble clic y volver atrás. | Se entiende si está ejecutando, falló o terminó; no se pierde la intención ni se duplica el cambio. |

### Qué NO se puede aprobar sólo con este recorrido

1. **Correo productivo:** TLS/autenticación del proveedor real, recepción en buzón
   controlado y evidencia de errores/throttling. Mailpit y SMTP250 no prueban esto.
2. **Limpieza automática productiva:** TTL/soft-delete no equivalen a destrucción;
   el inventario de recibos no implica un janitor habilitado ni borrado de backups.
3. **Infraestructura productiva:** HTTPS/ingress, cookies Secure, ACL de almacenes,
   despliegue, backup/restore y fencing requieren aceptación de ese destino real.
4. **Recuperación de factores:** existe una decisión pendiente sobre reemplazar
   factores durante recuperación. No se elimina el comportamiento aceptado sin
   reconciliar contrato, seguridad y la posibilidad de recuperar una llave perdida.
5. **Cobertura UI completa:** ciertas operaciones de autenticación/sesiones y
   activación de un segundo owner pueden requerir una ceremonia API, aunque
   exista el endpoint. Que figure en All operations no garantiza una interfaz
   capaz de construir una credencial WebAuthn; registra esa fricción como fallo
   de journey, no como PASS ni como permiso para saltarse la autenticación.

### Cómo registrar hallazgos

Para cada caso: ID, PASS/FAIL/BLOQUEADO/NO PROBADO, hora, cuenta de prueba sin
credenciales, tenant, pasos, resultado esperado/real, ID de petición si aparece
y captura saneada. Si un error dice éxito pero el estado no cambió, o una acción
denegada sí cambió datos, es un fallo crítico. Detén esa parte y conserva evidencia.

No adjuntes bearer, cookies, passkeys, contraseñas, proof de invitación ni recovery
codes. DevTools puede servir para observar status/correlación, pero los cuerpos de
auth y correos completos contienen secretos y deben excluirse del informe.

### Registro de preparación

- Reset previo autorizado: copia protegida dentro de Docker en
  `/tmp/request_engine_current-before-e2e-20261003.dump`; sólo se recreó la base
  local objetivo, no otras bases.
- Preflight de esta pasada: panel `/health/ready` y `/setup`, control/API
  `/health/ready` y control `/v1/setup`: HTTP200.
- Inicialmente se detectó código de migraciones aún en revisión por encima de
  la base0012. La sincronización y pruebas finales se registran después de
  ejecutarlas; no se atribuye al árbol nuevo la CI del commit anterior.
- Este documento no afirma haber ejecutado ninguna de las filas manuales.
- Sincronización posterior: `alembic upgrade head` aplicó
  `0013_temporary_proof_inventory` sobre la base5432; `unclaimed`, cero Principals
  y Organizations. No reset adicional ni janitor activado.
- Suite focal `uv run pytest tests/unit/admin_console
  tests/unit/test_staff_invitation_http.py
  tests/modules/tenancy/test_staff_command_input_contract.py
  tests/unit/platform/security/test_webauthn.py tests/unit/platform/secrets
  -q --tb=short`: **474 passed in36.09s**.
- Primera lane `uv run python scripts/ci/ci_jobs.py python-quality --log-dir
  .ci/admin-manual-preflight-quality --summary-output
  .ci/admin-manual-preflight-quality.json`: todos los pasos PASS;
  **201 arquitectura /973 unit /656 módulos**. Correcciones posteriores del
  guard del recorder y soporte de delivery necesitan sus pruebas/re-proof; esta
  corrida no certifica un snapshot posterior ni un SHA publicado.
