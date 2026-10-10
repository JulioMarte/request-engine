# Revisión de sesiones y WebAuthn — 2026-10-03

## Reporte simple (para humanos)

Se encontró y corrigió un fallo funcional: al crear una llave de acceso, el
sistema no exigía que esa llave sirviera para iniciar sesión sin escribir un
usuario. La pantalla de administración sí ofrece esa entrada. Ahora las nuevas
llaves deben admitirla; las antiguas no se modifican ni se borran. Un dispositivo
que no pueda crear esa clase de llave podrá rechazar el alta, en vez de crear una
llave que después no aparezca en la entrada principal.

Las 45 pruebas locales seleccionadas pasan. Eso no prueba un navegador real ni
certifica producción. No se usó ni modificó ninguna base de datos en esta pasada.
La revisión también dejó dos puntos para revisar: diferencias entre respuestas
de entrada con usuario y la política de reemplazar una llave perdida durante
recuperación. El segundo comportamiento sí está aceptado y probado en una prueba
vigente; bloquearlo puede impedir la recuperación. No se cambió ninguno de esos
flujos. Se retiró una propuesta de bloqueo antes de aplicarla a una base de datos.

## Reporte técnico (detallado)

### Alcance y procedencia

Fuente de revisión: `e4f65b59eae4fcc032f3b7effc0550c165fe6ee7`, rama
`feature/admin-console`. Base declarada de los paquetes:
`1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`.
Paquetes inspeccionados en `.ci/admin-replay-batch-exact-evidence/`, formato
`quality-evidence/v2`, `test_mode=BRANCH_HEAD`, `source_head_sha=tested_sha=e4f65b59…`.
Los resultados de arquitectura, lint, formato, tipos, unidades y módulos figuran
como `pass` en esos paquetes; esta revisión no los volvió a ejecutar como lane
completo ni convierte ese registro en prueba de PostgreSQL o de navegador.

Se leyeron las unidades de sesión/autenticación, el store WebAuthn, las ceremonias
y sus llamadas de alta/login/step-up; el SQL completo de los finalizadores de
registro, autenticación, step-up y autenticación discoverable; la proyección SQL
de sesión y finalización de recovery; la materialización de identidad a autoridad
tenant/platform y su filtro de recuperación; el almacén BFF y las rutas de login.
Contratos: `current-guarantees.toml`, `self-organization-discovery.md`,
`self-authority-inspection.md`, las decisiones P2 de
`instance-claim-platform-owner-plan.md`, instrucciones de migración/testing y
el playbook/protocolo de revisión semántica. Los checkpoints históricos de auth
no reemplazan el rebaseline vigente ni sus garantías.

No se cambiaron migraciones, ACLs, recuperación, autoridad tenant, cookies,
sesiones persistidas, endpoints ni execution paths. No se realizaron commit/push.
Los cambios de otros agentes en OpenBao/retención fueron preservados.

### Hallazgo funcional W-01 — corregido, prueba local

`WebAuthnService.begin_registration` delegaba a `Fido2Server.register_begin`
sin `resident_key_requirement`. La reproducción con la dependencia instalada
devolvió `authenticatorSelection.residentKey=discouraged` y
`requireResidentKey=False`. No garantiza una credencial discoverable, aunque
`NativeWebAuthnLoginService.begin_login(login_handle=None)` usa precisamente una
ceremonia discoverable con allow-list vacía.

Cambio: `src/request_engine/platform/security/webauthn.py` incorpora
`ResidentKeyRequirement.REQUIRED` en el mismo constructor de opciones y en su
Protocol tipado. Setup y alta autenticada comparten este primitivo; no hay una
segunda implementación en el panel. Se preservan la política UV, RP/origen,
challenge, exclusiones y verificación criptográfica.

Prueba: `tests/unit/platform/security/test_webauthn.py`,
`test_begin_options_are_json_serializable`, exige las opciones exactas
`residentKey=required`, `requireResidentKey=True`, `userVerification=required`.
Omitir el parámetro vuelve roja esa prueba. Los round trips existentes siguen
verificando firma/origen/challenge/UV y estado de la librería.

Compatibilidad: afecta únicamente futuras opciones de registro. No convierte ni
elimina credenciales antiguas; una antigua no-discoverable mantiene la alternativa
handle-first. No se fija attachment a plataforma ni se excluyen llaves roaming
capaces de almacenar credenciales residentes. No hay DDL ni backfill.
Limitación: la prueba software no demuestra compatibilidad de hardware concreto,
Bitwarden o Chrome. El software-authenticator no modela exhaustivamente capacidad
residente; por eso la prueba del requisito usa las opciones reales de fido2.

### Hallazgos estáticos pendientes, no exploits demostrados

**W-02 — diferencia de cardinalidad del allow-list.**
`NativeWebAuthnLoginService` construye exactamente una entrada decoy para un
handle desconocido; `NativeWebAuthnAuthService.begin_authentication` devuelve
todas las credenciales activas para el handle real. Con varias credenciales, las
respuestas tienen distinta cardinalidad. Esto contradice el comentario que
promete una única entrada y merece confrontarse con
`INV-NATIVE-WEBAUTHN-LOGIN-001`. La observación es estática; no se realizó una
prueba HTTP/PG de enumeración ni se midió timing. El recorrido discoverable sin
handle no tiene este selector. No se debe corregir truncando credenciales al azar:
eso podría impedir el login con otra llave legítima. La selección de una política
uniforme requiere decisión del owner y evidencia de múltiples llaves.

**W-03 — decisión de producto pendiente; no es un defecto demostrado.**
Los handlers de registro comprueban una sesión nativa válida y extraen su propia
identidad, pero no aplican un guard de recovery/freshness. El finalizador SQL de
registro valida autoridad/identidad activas y el challenge; no consulta recovery
posture. `complete_recovery` requiere una sesión reciente phishing-resistant,
mientras el SQL `complete_native_recovery` comprueba la existencia de una llave
activa. Es una combinación que requiere revisión del contrato de "factor fuerte
aceptado": distinguir el factor previamente establecido de un factor creado
durante recuperación, sin bloquear el onboarding del primer factor legítimo.

La inspección posterior de
`tests/e2e/test_native_webauthn_login_http.py::test_offline_recovery_restricts_sensitive_authority_until_webauthn_completion`
mostró una expectativa explícitamente positiva: la sesión restringida registra
una llave de reemplazo, hace step-up con ella y completa recuperación antes de
recuperar la autoridad sensible. Se inspeccionó esa prueba; no se volvió a ejecutar
en esta pasada. `INV-NATIVE-RECOVERY-POSTURE-001` exige un factor fuerte aceptado,
pero no exige explícitamente el factor original previamente establecido.

La propuesta de exigir exclusivamente un factor preexistente no fue ratificada:
puede dejar sin salida a quien perdió su llave. Los gates experimentales de API,
servicio y store, su migración y pruebas nuevas se retiraron antes de cualquier
DDL. No queda una nueva policy de recuperación implementada. El owner debe
resolver primero el reemplazo de factores perdidos y su autoridad aceptada; una
modificación posterior necesitaría evidencia positiva y negativa de la transición
real. No se probó una cadena de ataque ni se afirma un exploit verificado. Un guard
solamente en el BFF sería insuficiente y no es una recomendación válida.

### Disposiciones semánticas de los candidatos revisados

`human_verdict: null` en todos: no hay aprobación humana inferida de los tests.

| Candidato / trigger | Hecho determinista del paquete | Veredicto | Confianza |
| --- | --- | --- | --- |
| QR-a8d753673d5e / QR-FSIZE-001 | `0002_discoverable_webauthn_login.py`: 322 LOC | HEALTHY_AS_IS | alta |
| QR-6e4284cad14e / QR-FSIZE-001 | `webauthn_store.py`: 386 LOC, delta +40 | HEALTHY_AS_IS | alta |
| QR-e2cd30800a26 / QR-FSIZE-001 | `native_webauthn_auth.py`: 487 LOC, delta +82 | REVIEW_CONCERN | media |
| QR-93bd1bd0b60b / QR-FSIZE-001 | `native_auth.py`: 1040 LOC, delta +8 | REVIEW_CONCERN | media |
| QR-764f3c852353 / QR-CPLX-001 | `create_native_auth_router`: McCabe 53 | REVIEW_CONCERN | media |

Propiedad protegida común: cohesión, localidad y carga real de razonamiento; los
números son sensores no bloqueantes, nunca prueba de inseguridad.
Resultados de arquitectura considerados: los nueve `architecture_results`
de cada paquete declaran `pass`; no se concede waiver de ninguna garantía HARD.

**QR-a8d753673d5e.** La migración contiene upgrade/downgrade de una sola extensión
de ceremonia y su finalizador. El SQL resuelve identidad desde credencial,
revalida autoridad/identidad/credencial, serializa consumo y emisión en una
transacción, deriva assurance y revoca PUBLIC. Contrargumento: el texto SQL
duplicado aumenta navegación, pero extraer el historial inmutable a helpers
compartidos introduciría otra autoridad/versionado. Acción: conservar estructura;
verificación necesaria para seguridad: pruebas PG de consumo, revocación y
concurrencia, no ejecutadas aquí. HEALTHY_AS_IS refiere estructura, no certificación.

**QR-6e4284cad14e.** Store lineal que traduce un port tipado a funciones auth
estrechas, cada efecto en transacción explícita; no replica política de negocio.
Contrargumento: campos repetidos y many methods dificultan cambios de esquema,
pero son DTOs explícitos de un mismo boundary y un dispatcher genérico perdería
esa comprobación. Acción: mantener; no fragmentar por LOC ni añadir repositorios
genéricos. Verificación: contratos de privilegios y persistencia PG siguen siendo
necesarios independientemente de esta disposición.

**QR-e2cd30800a26.** Registro, login bound/discoverable y step-up son fases
cohesivas del mismo protocolo; verificación criptográfica sucede fuera del lock,
finalización autoritativa en el store. Contrargumento: la localidad facilita
examinar shared scope/credential validation. W-02 requiere revisar exposición;
W-03 es una decisión de producto pendiente, no un defecto demostrado. Acción:
owner review antes de extracción o policy change; no duplicar ceremonias ni mover
reglas al panel. Verificación pendiente: varias llaves y recovery completo por
superficie real, manteniendo onboarding.

**QR-93bd1bd0b60b / QR-764f3c852353.** La fábrica agrupa varios ciclos de vida
auth, DTOs y traducciones de error; el score incorpora muchos handlers y bloques
de registro independientes, no un algoritmo monolítico de 53 ramas ejecutadas.
Contrargumento: la agrupación conserva las dependencias de trust boundary y
evita una segunda policy registry. La revisión relevante es comparar gates entre
registro, recovery y session actions (W-03), no el umbral. Recomendación: revisar
matriz semántica de precondiciones y uniformar gates solamente tras decisión del
owner. No separar mecánicamente endpoints, debilitar `current-guarantees` ni
aprobar seguridad por un score menor. Verificación: exact-head HTTP/PG negativa y
positiva sobre cada gate; esta pasada no la ejecutó.

### Evidencia ejecutada y límites

Entorno: Windows PowerShell, Python administrado por `uv`, dependencia fido2 del
lock vigente; comandos desde el workspace. No se imprimieron credenciales.

```text
uv run pytest tests/unit/platform/security/test_webauthn.py tests/unit/platform/security/test_native_session.py tests/unit/platform/security/test_identity_resolution.py tests/unit/platform/security/test_privileged_authentication.py -q
45 passed in 0.48s

uv run ruff check src/request_engine/platform/security/webauthn.py tests/unit/platform/security/test_webauthn.py
All checks passed!

uv run ruff format --check src/request_engine/platform/security/webauthn.py tests/unit/platform/security/test_webauthn.py
2 files already formatted

uv run pyright src/request_engine/platform/security/webauthn.py tests/unit/platform/security/test_webauthn.py
0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/platform/security -q
117 passed in 3.90s
```

Después de retirar W-03, `git diff --stat --` sobre `native_auth.py`,
`webauthn_store.py`, `native_webauthn_auth.py`, `test_webauthn_persistence.py` y
`test_setup_registration_binding.py` no produjo salida: esos cinco archivos
quedaron idénticos a HEAD. Se eliminaron únicamente los borradores nuevos propios:
`0013_webauthn_recovery_enrollment.py`, `test_native_passkey_enrollment.py` y
`native-passkey-enrollment-policy.md`. Ninguna migración de esta propuesta se
aplicó. La prueba de 117 unidades corresponde al estado después de retirarla.

La reproducción previa `uv run python -c` del constructor de registro imprimió
`residentKey=discouraged`, `requireResidentKey=False`; la prueba posterior verifica
`required/True`. Un intento de reproducción del allow-list con `python -c` falló
por quoting con SyntaxError y no cuenta como evidencia positiva de W-02.

Estado de re-proof: **PENDING_REPROOF** para la lane completa `python-quality` y
exact-head CI tras el futuro commit; narrow local verde para W-01. Ninguna prueba
PG, navegador, SMTP, backup/restore ni despliegue se ejecutó aquí. El fallo ACL de
una corrida anterior de otra revisión no se atribuye a e4f65b59: en esta fuente
`runtime_table_contract.py` ya clasifica `native_identity_recovery_facts` como
tabla global privada. No se ampliaron grants para ocultar esa discrepancia antigua.
