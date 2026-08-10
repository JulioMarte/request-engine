# Request Engine V2 — lecciones preservadas de V1 y estrategia de migración

> **Estado:** documento V2 vigente y complementario a `00-product-definition.md` y `01-architecture-v2.md`.
>
> Este documento conserva únicamente las decisiones de V1 que siguen siendo útiles después de la redefinición de Request Engine. Las implementaciones, endpoints, nombres de tablas, vendors y procedimientos operacionales específicos de V1 están archivados en `v1-ideas-viejas/` y no son autoritativos para V2.

---

## 1. Objetivo

V1 probó varias ideas valiosas alrededor de capacity, queues, holidays, security, outbox e integraciones. V2 cambió profundamente el producto y la arquitectura —PostgreSQL/Python, `Reservation` como vocabulario canónico, Request/OfferingSelections, payments provider-agnostic y boundaries más estrictos— pero no debe perder invariantes que ya habían demostrado valor.

La regla de este documento es:

> **Preservar la lección; no preservar accidentalmente la implementación que la produjo.**

---

## 2. Reservation options: efímeras, opacas y no autoritativas

V1 utilizaba ofertas de disponibilidad opacas, de corta vigencia y de un solo uso. La idea sigue siendo correcta, pero V2 no fija universalmente cinco minutos ni obliga a que toda `ReservationOption` tenga exactamente el mismo mecanismo.

Principios V2:

- `ReservationOption` es una lectura/propuesta, nunca un commitment de capacity;
- cuando se expone como token utilizable para confirmar, debe ser opaco y no permitir al cliente alterar resource IDs, price snapshots o capacity internals;
- puede tener `expires_at` y, cuando el flujo lo requiera, semántica de single-use;
- el TTL pertenece a policy/configuration, no a un número global hardcoded;
- `ConfirmReservation` siempre revalida capacity, aunque la option no haya expirado;
- si se necesita proteger capacity durante confirmación/pago, se crea `CapacityHold` explícito.

No reintroducir un estado ambiguo tipo `pending_confirmation` que consume capacity sin que exista un `CapacityHold` o una `Reservation` autoritativa.

---

## 3. Queue authority y estimaciones

V1 demostró una distinción importante entre **estimación de espera** y **posición autoritativa en una queue**.

En V2:

```text
estimated wait / candidate position
!=
QueueEntry authoritative state
```

La `AdmissionPolicy` decide cuándo puede existir una `QueueEntry`:

- una queue física puede exigir `CheckIn` antes de crear ticket/posición;
- una remote queue puede permitir entrada antes de presencia física;
- antes de que exista una `QueueEntry` válida, cualquier posición o ETA es sólo una estimación y debe presentarse como tal.

Cambios manuales de prioridad deben conservar como mínimo:

```text
principal
reason
previous priority/order
new priority/order
timestamp
audit/event
```

Una IA no recibe una tool genérica para modificar prioridad arbitrariamente.

---

## 4. PII sensible y búsqueda segura

V1 utilizó un patrón útil para identificadores sensibles que deben buscarse por igualdad sin conservar plaintext innecesario.

Cuando el threat model de V2 lo justifique, usar conceptualmente:

```text
ciphertext        → confidencialidad en reposo
blind index/HMAC  → equality lookup
masked display    → presentación segura
key version       → rotación/migración
```

AES-GCM + HMAC fue una implementación V1 razonable, pero el algoritmo/servicio concreto debe fijarse mediante ADR de seguridad y puede cambiar.

Reglas:

- no cifrar indiscriminadamente todos los campos si no existe necesidad/threat model;
- secretos y claves viven fuera de las tablas de dominio;
- scopes de lectura de PII sensible son independientes de scopes operacionales normales;
- no colocar PII completa, comprobantes financieros, GPS trails o secretos en logs/webhooks generales;
- rotación de claves debe ser posible sin perder trazabilidad.

---

## 5. Confirmaciones, reminders y auto-release

V1 tenía una policy específica de reminders multicanal (T-72/T-48/T-30 y posible liberación T-24). **Los tiempos exactos no se preservan como arquitectura.** Sí se preservan las siguientes reglas:

1. reminders/notifications son side effects y se entregan mediante outbox/adapters;
2. retry de comunicación nunca vive dentro de la transacción autoritativa de Reservation;
3. ausencia de respuesta no debe cancelar/liberar capacity a menos que una policy versionada lo autorice explícitamente;
4. si una policy permite auto-release, debe conservar evidencia suficiente de la condición que la activó;
5. una policy tipo `never_auto_cancel`/equivalente debe poder impedir liberación automática cuando el Offering/organization lo requiera;
6. ventanas horarias de contacto pertenecen a communication policy/local timezone, no al scheduler central.

Si V2 implementa reminders/confirmation automation, debe hacerlo como policy/capability separada, no como estados adicionales dentro de `Reservation`.

---

## 6. Holiday provenance y revisión

V1 correctamente trató los feriados como **datos con provenance**, no como verdad universal de que el negocio está cerrado.

`HolidayDate`/holiday source debería poder conservar cuando corresponda:

```text
jurisdiction country
subdivision/region nullable
canonical date
observed date nullable
name
source/provider/reference
source version/fetched_at when imported
review status when human review is required
metadata
```

Reglas V2:

- holiday detected/imported != organization closed;
- `HolidayPolicy` decide `closed_by_default`, `normal_schedule` o `special_hours`;
- ausencia de respuesta humana no debe inventar un cierre si la policy no lo establece;
- modificar disponibilidad futura y resolver Reservations ya confirmadas son operaciones separadas;
- cambios que invalidan capacity comprometida entran por `ReservationDisruption`, no por cancelación silenciosa.

---

## 7. External callbacks: autenticidad, anti-replay e idempotencia

V1 usaba callbacks firmados con HMAC sobre `timestamp.body`. V2 conserva el principio, no necesariamente ese wire format para todos los providers.

Todo callback que pueda producir una mutación autoritativa debe considerar:

```text
authentication/signature
anti-replay/timestamp or provider mechanism
provider event deduplication
schema/version validation
idempotent application command
source attribution
audit
```

Texto libre, transcription, browser redirect o un mensaje de un integration adapter no adquiere autoridad sólo por llegar a un webhook.

---

## 8. Outbox acknowledgment semantics

Una lección operacional importante de V1 fue que un consumer no debe devolver éxito si todavía no aceptó realmente el evento.

Para webhooks/outbox delivery:

> **Un `2xx` significa aceptación durable/exitosa según el contrato del consumer, no simplemente “recibí HTTP”.**

Si el consumer aún no puede procesar/guardar el evento:

- devolver failure/retryable status según contrato;
- no marcar la entrega como finalizada;
- conservar attempts/backoff/dead-letter state;
- deduplicar retries mediante event/idempotency IDs.

Un “safety gate” que falla cerrado es preferible a perder silenciosamente un evento por responder `2xx` demasiado temprano.

---

## 9. Conversation y attachments no son source of truth del trabajo

V1 ya había aprendido una frontera que V2 formalizó:

```text
Conversation system
= messages, attachments, channel UX

Request Engine
= structured intent, policies, authoritative operational state, outcomes and audit
```

Chatwoot, WhatsApp, email u otro channel pueden conservar conversación/adjuntos. Request Engine guarda referencias y sólo copia/snapshottea aquello que necesita como evidencia o input estructurado del dominio.

Esto preserva:

> **Conversation is context. Request is work.**

---

## 10. Agent flow: options, not internal graphs

V1 limitaba al agente a un flujo estrecho de catálogo → availability → opciones → commit. La nomenclatura concreta (`catalog.search`, `booking.create`) está obsoleta, pero la lección sigue vigente.

Agent tools V2 deben:

- ser goal-oriented;
- devolver pocas opciones relevantes cuando sea apropiado;
- ocultar resource graphs, locks y provider internals;
- trabajar con public/opaque IDs válidos;
- requerir idempotency en writes reintentables;
- revalidar estado autoritativo al ejecutar;
- no confiar en availability antigua almacenada en contexto del LLM.

El LLM interpreta y selecciona entre acciones permitidas; application/domain layer decide si la acción sigue siendo válida.

---

## 11. Provisioning e integrations no son core

V1 acopló parte importante del onboarding a Chatwoot/Evolution/n8n provisioning. Eso fue útil para un piloto, pero no se preserva como responsabilidad central.

En V2:

```text
Chatwoot
Evolution / Meta
LiveKit
Twilio
n8n
maps
tracking
PSPs
banks
```

son adapters/integrations.

Si existe provisioning automatizado, vive en un módulo/integration explícito y no redefine `Request`, `Reservation`, `Payment`, `Contact` ni el workflow engine.

---

## 12. Migración de V1 Convex a V2 PostgreSQL

La implementación V1 existente contiene conocimiento y posiblemente datos útiles. No eliminarla sólo porque V2 cambia de stack.

La estrategia recomendada es **migración verificable y reversible**, evitando dual-write permanente.

### Fase 1 — congelar semántica V1

- documentar commit/tag de referencia;
- no añadir nuevas features de dominio a V1 salvo fixes necesarios;
- identificar tablas/functions que son verdaderamente usadas;
- exportar schema/data de prueba representativos;
- conservar backup verificable.

### Fase 2 — construir V2 en paralelo

Implementar PostgreSQL/FastAPI con contratos V2 sin modificar los datos V1.

Crear mappings explícitos:

```text
legacy_system
legacy_entity_type
legacy_id
v2_public_id
migration_batch
```

Los IDs Convex/V1 nunca se convierten en PK/public IDs de V2.

### Fase 3 — importación inicial

Migrar por dependency order, por ejemplo:

```text
Organizations
Contacts
Locations
Offerings
Resources / schedules
Requests / selections
Reservations / allocations
queues/waitlists where still meaningful
external mappings/audit references
```

No migrar automáticamente healthcare-specific o provisioning-specific entities al core V2. Evaluarlas como módulos/legacy data.

### Fase 4 — equivalence/shadow validation

Comparar, según el dominio:

- row/entity counts;
- tenant ownership;
- public/external mappings;
- representative schedule results;
- historical Reservation snapshots;
- capacity conflicts;
- queue/waitlist state where meaningful;
- timestamps/timezones;
- audit/event samples.

Ejecutar los edge-case tests V2 contra datos migrados de muestra.

### Fase 5 — cutover controlado

Preferencia:

1. anunciar maintenance/cutover window si hace falta;
2. congelar writes V1;
3. ejecutar delta migration final;
4. verificar checksums/counts/invariants;
5. cambiar API/agents/UI al V2;
6. monitorizar errores y reconciliation;
7. mantener V1 read-only durante una ventana de rollback.

Evitar dual-write bidireccional salvo necesidad extrema: multiplica los escenarios de inconsistencia.

### Fase 6 — retiro

Sólo después de criterios de aceptación explícitos:

- export/backup final;
- conservar archive/tag;
- retirar secrets/integrations V1;
- deshabilitar endpoints/writes;
- eliminar tablas/deployments sólo en cambio posterior aprobado.

---

## 13. Qué NO se preserva de V1 como arquitectura vigente

Las siguientes decisiones quedan históricas:

```text
Convex como source of truth objetivo
Request Engine = sistema de agenda
booking.* como vocabulario canónico
fixed_time / arrival_window / class_session como ontología central
healthcare/ARS/exequátur en el core
n8n como workflow/orchestrator autoritativo
Chatwoot/Evolution provisioning como responsabilidad principal
T-72/T-48/T-30/T-24 como política global
cinco minutos como TTL universal
queue física obligatoria para todos los verticales
```

Algunas pueden existir como configuraciones, adapters o módulos de un cliente; ninguna debe volver a definir el core V2.

---

## 14. Criterio de preservación

Cuando aparezca una idea de V1, preguntar:

1. ¿Es un invariante independiente de Convex/vendor/vertical?
2. ¿Ya está representado por una primitiva V2 más precisa?
3. ¿Pertenece a policy/configuration en vez de core?
4. ¿Es sólo una decisión operacional de julio de 2026?
5. ¿Mantenerla reduce riesgo real o sólo conserva complejidad histórica?

Sólo las ideas que sobrevivan estas preguntas entran en V2.
