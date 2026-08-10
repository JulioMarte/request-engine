# Request Engine — definición de producto y norte arquitectónico

> **Estado:** documento fundacional para la siguiente iteración de Request Engine.
>
> Este documento define **qué es Request Engine, qué no es, qué invariantes conserva de V1 y qué límites deben guiar el rediseño**. Las decisiones de infraestructura concretas (por ejemplo PostgreSQL vs Convex) deben resolverse mediante ADRs separados y no cambiar esta definición del producto.

---

## 1. La idea original

La idea de Request Engine es deliberadamente más general que un sistema de agenda, un CRM, un chatbot o un agente de IA.

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Una formulación más precisa:

> **Una persona, sistema o agente solicita un resultado a una organización. Request Engine convierte esa intención en una solicitud estructurada, determina qué workflow corresponde, coordina las acciones deterministas necesarias y mantiene el estado hasta llegar a un resultado verificable.**

Request Engine no existe para “tener conversaciones”. Existe para **convertir intención en trabajo estructurado y trazable**.

---

## 2. El problema que resuelve

Los negocios reciben solicitudes desde muchos canales:

- website;
- formularios;
- teléfono;
- WhatsApp;
- chat;
- redes sociales;
- agentes de IA;
- empleados;
- APIs de terceros.

Aunque el canal cambia, el negocio necesita responder preguntas similares:

1. ¿Quién está pidiendo algo?
2. ¿Qué quiere conseguir?
3. ¿Qué información falta?
4. ¿Qué reglas del negocio aplican?
5. ¿Qué workflow debe ejecutarse?
6. ¿Qué acciones pueden realizarse automáticamente?
7. ¿Qué requiere aprobación, confirmación o intervención humana?
8. ¿Cuál fue el resultado final?

Request Engine debe proporcionar una capa común para resolver esas preguntas sin duplicar lógica en cada website, bot, workflow de n8n o agente de voz.

---

## 3. La unidad fundamental: `Request`

Un `Request` representa **una intención concreta que una organización debe atender**.

Ejemplos:

```text
"Quiero una cita para limpieza dental"
"Necesito que un técnico revise una fuga hoy"
"Quiero una cotización"
"Necesito que me llamen"
"Quiero reservar una evaluación de QuisqueyaTech"
"Quiero cambiar mi cita"
```

El core no debe asumir que quien solicita es un `patient`, `student`, `tenant`, `bride` o `customer` de una industria específica.

Debe trabajar con conceptos neutrales:

- `organization`
- `contact`
- `request`
- `requestType`
- `workflow`
- `principal`
- `event`
- `fulfillment`

Las palabras específicas de un vertical pertenecen a la UX, configuración o módulos de dominio, no al core.

---

## 4. Modelo mental del sistema

```text
                              CHANNELS

       Website       WhatsApp       Voice AI       Human UI       API
          │              │              │              │            │
          └──────────────┴──────────────┴──────────────┴────────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │       INTAKE        │
                              │ normalize / identify│
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │       REQUEST       │
                              │ canonical intention │
                              └──────────┬──────────┘
                                         │
                                  classify + policy
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │      WORKFLOW       │
                              │ deterministic rules │
                              └──────────┬──────────┘
                                         │
                          ┌──────────────┼──────────────┐
                          ▼              ▼              ▼
                     Scheduling        Quote         Handoff
                     / Booking       / Estimate      / Callback
                          │              │              │
                          └──────────────┼──────────────┘
                                         ▼
                              ┌─────────────────────┐
                              │     FULFILLMENT     │
                              │ outcome + evidence  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                                    EVENTS / AUDIT
```

Los canales son **adaptadores**. No deben contener la lógica real del negocio.

---

## 5. Ciclo de vida conceptual de una solicitud

El lifecycle exacto podrá evolucionar, pero el core debe poder representar como mínimo:

```text
received
   ↓
understanding
   ↓
collecting_information
   ↓
ready
   ↓
executing
   ↓
waiting_external | waiting_confirmation | waiting_human
   ↓
completed | failed | cancelled | handoff
```

Reglas importantes:

- una conversación puede producir cero, uno o varios requests;
- un request puede sobrevivir al canal que lo originó;
- cambiar de WhatsApp a teléfono no crea necesariamente un request nuevo;
- el estado del request no debe depender del estado de Chatwoot, LiveKit, Twilio o n8n;
- cada transición importante debe ser auditable.

---

## 6. `RequestType`: qué puede pedir alguien

Cada organización debe poder declarar los tipos de solicitudes que sabe atender.

Ejemplos:

```text
book_consultation
emergency_service
request_quote
schedule_cleaning
request_callback
reschedule_booking
cancel_booking
```

Un `RequestType` debería poder describir conceptualmente:

```text
id
organizationId
name
inputSchema
workflowKey
policies
status
version
```

El `inputSchema` define la información necesaria. El `workflowKey` determina qué implementación procesa la solicitud.

**No construir inicialmente un BPMN genérico ni un editor visual universal de workflows.** La primera versión debe favorecer workflows tipados, versionados y testeables en código/configuración.

---

## 7. Workflow: decisión y ejecución

Request Engine debe responder:

> Dado este `Request`, esta organización, estas políticas y este contexto, ¿qué debe ocurrir ahora?

Un workflow puede:

1. pedir información faltante;
2. consultar una capability;
3. ofrecer opciones;
4. ejecutar una operación;
5. solicitar confirmación;
6. esperar un callback;
7. crear una tarea humana;
8. completar la solicitud;
9. fallar de forma recuperable;
10. hacer handoff.

Ejemplo:

```text
Request: "Necesito un plomero mañana"

identify contact
      ↓
classify → emergency_service
      ↓
collect address + problem type
      ↓
search scheduling availability
      ↓
present options
      ↓
customer selects option
      ↓
create booking
      ↓
send confirmation
      ↓
Request completed
```

El workflow no debe conocer detalles de WhatsApp o LiveKit. Recibe y produce datos estructurados.

---

## 8. Capabilities y módulos

Request Engine debe ser extensible mediante **capabilities deterministas**.

Ejemplos:

```text
scheduling.searchAvailability
scheduling.createBooking
scheduling.rescheduleBooking
scheduling.cancelBooking

quotes.createDraft
quotes.send

contacts.upsert

notifications.send

handoff.createTask
```

Un workflow consume capabilities. Los canales y agentes consumen Request Engine.

Esto produce la dependencia correcta:

```text
LiveKit ───────┐
WhatsApp ──────┤
Website ───────┼──► Request Engine ───► capability modules
Admin UI ──────┤
External API ──┘
```

Y evita la dependencia incorrecta:

```text
Request Engine
   ├── knows LiveKit internals
   ├── provisions Chatwoot
   ├── provisions Evolution
   ├── depends on n8n
   └── contains vertical-specific business models
```

---

## 9. Qué pertenece al core

El núcleo inicial debe ser pequeño.

### Tenancy e identidad operacional

- organizations;
- principals / credentials;
- contacts;
- organization-scoped configuration.

### Requests

- request types;
- requests;
- request state;
- structured input/output;
- workflow selection;
- workflow execution state.

### Platform primitives

- events;
- audit;
- idempotency;
- webhooks/outbox;
- API authentication and scopes;
- versioned contracts.

### Módulos iniciales, fuera del core puro

- scheduling / booking;
- forms / intake.

Estos módulos pueden vivir en el mismo deploy y repositorio. “Fuera del core” significa **boundary de dominio**, no microservicio obligatorio.

---

## 10. Qué NO pertenece al core

Estas funcionalidades pueden existir como módulos o integraciones, pero no deben contaminar las abstracciones base:

- seguros / ARS;
- expedientes clínicos;
- exequátur o licencias profesionales;
- conceptos `patient`, `guardian`, `provider` específicos de healthcare;
- Chatwoot provisioning;
- Evolution provisioning;
- Meta WhatsApp provisioning;
- n8n workflows;
- LiveKit workers;
- Gemini / LLM provider details;
- SIP / PBX implementation;
- prompts específicos de agentes;
- lógica específica de una sola industria;
- inventario;
- billing/accounting;
- un CRM completo.

Request Engine puede integrarse con esos sistemas, pero no debe convertirse en ellos.

---

## 11. La IA no es la autoridad del sistema

Request Engine debe funcionar aunque no exista un LLM.

La IA puede ayudar a:

- interpretar lenguaje natural;
- clasificar intención;
- extraer campos;
- explicar opciones;
- decidir qué tool llamar dentro de límites explícitos.

Pero las operaciones críticas deben ser deterministas:

```text
LLM proposes intent
      ↓
Request Engine validates
      ↓
workflow determines allowed action
      ↓
typed capability executes
      ↓
transaction verifies invariants
      ↓
event records outcome
```

Un texto libre o una transcripción nunca debe modificar por sí solo una reserva, pago, identidad u otro estado crítico.

---

## 12. Request Engine es API-first y headless

La API es una interfaz principal del producto, no un detalle de implementación.

Consumidores esperados:

- QuisqueyaTech.com;
- websites de clientes;
- booking widget;
- forms widget;
- LiveKit agents;
- WhatsApp/Chatwoot adapters;
- n8n;
- admin console;
- software de terceros.

Por tanto:

- UI pública y admin deben consumir los mismos contratos que otros clientes cuando sea razonable;
- las reglas de negocio no deben vivir exclusivamente en componentes React;
- contratos request/response deben ser versionados;
- schemas, validación, tipos y OpenAPI deben derivar idealmente de una fuente común;
- evitar un router HTTP monolítico basado en grandes cadenas de `if (path === ...)`.

---

## 13. Multi-tenancy desde el primer día

Toda entidad que pertenezca a un negocio debe estar claramente scoped a una organización.

Principio:

```text
credential
    ↓
resolve organization + principal + scopes
    ↓
all domain operations execute inside that scope
```

No confiar en un `organizationId` arbitrario enviado por el browser cuando la identidad de la credencial ya determina el tenant.

Deben existir al menos dos clases de acceso:

### Public/browser access

Para widgets, forms y websites. Permisos limitados, orígenes permitidos y operaciones explícitamente públicas.

### Secret/server access

Para workers, agents, backends e integraciones. API keys privadas, scopes y rotación.

Nunca colocar una secret API key organizacional dentro de JavaScript público.

---

## 14. Eventos, outbox e integraciones

Conservar el principio de V1:

> **Una transacción interna no debe depender de que un sistema externo responda correctamente.**

Patrón preferido:

```text
transaction commits
      ↓
domain event / outbox entry
      ↓
async delivery
      ↓
external provider
      ↓
idempotent callback
      ↓
state reconciliation
```

Requisitos:

- event IDs únicos;
- versionado de eventos;
- retries explícitos;
- deduplicación;
- callbacks firmados cuando corresponda;
- external IDs son referencias, nunca identidad primaria del dominio.

---

## 15. Idempotencia

Conservar de V1.

Cualquier operación que pueda repetirse debido a red, agentes, webhooks o retries debe soportar idempotencia cuando sea relevante.

Especialmente:

- create request;
- create booking;
- reschedule;
- payment-like actions futuras;
- callbacks;
- provisioning externo;
- webhook consumption.

Una misma idempotency key con un payload diferente debe producir conflicto explícito.

---

## 16. Auditoría y trazabilidad

Cada request debe responder:

```text
Who requested this?
What was understood?
What information was collected?
Which workflow/version handled it?
What decisions were taken?
Which principal/tool performed each mutation?
What external events occurred?
What was the final outcome?
```

No depender únicamente de application logs para reconstruir negocio.

Logs sirven para diagnóstico técnico. Events/audit sirven para historia operacional.

---

## 17. Tiempo y scheduling

Las decisiones correctas de V1 que deben conservarse dentro del módulo de scheduling:

- timestamps persistidos como instantes UTC;
- zonas IANA en entidades que interpretan tiempo local;
- disponibilidad no equivale a reserva;
- `booking.create` revalida disponibilidad/capacidad transaccionalmente;
- idempotency en creación/reprogramación;
- buffers y recursos forman parte del conflicto real;
- snapshots comerciales protegen historial frente a cambios futuros del catálogo;
- external side effects no ocurren dentro de la transacción de booking.

### Opaque offers

La idea de una oferta temporal de disponibilidad es válida para agentes y operaciones que requieren seleccionar una opción previamente calculada.

Sin embargo, V2 debe separar conceptualmente:

```text
availability.read       → lectura barata / no necesariamente persistente
booking.offer.create    → intención temporal que puede persistirse
booking.create          → revalidación + commit
```

No toda exploración de calendario debe crear filas persistentes.

---

## 18. PII y seguridad

Conservar de V1 cuando sea necesario:

- cifrado de PII sensible en reposo a nivel de aplicación cuando el threat model lo justifique;
- blind indexes para búsquedas de igualdad sobre datos cifrados;
- valores enmascarados para UI;
- key versioning para rotación;
- scopes específicos para lectura/escritura sensible;
- secretos fuera del frontend y del repositorio.

Pero no incorporar PII específica de healthcare al core hasta que un módulo concreto la necesite.

---

## 19. Public IDs e IDs externos

Conservar el patrón de public IDs separados de los IDs internos.

Ejemplos conceptuales:

```text
req_...
org_...
cnt_...
bkg_...
```

Integraciones externas deben almacenarse como mappings/references:

```text
provider
externalType
externalId
internalEntityType
internalPublicId
```

Un `chatwootConversationId`, `twilioCallSid`, `livekitRoomName` o ID de Evolution nunca debe convertirse en la identidad primaria de un Request.

---

## 20. Forms / Intake

V2 no debe empezar construyendo un competidor de Typeform o Jotform.

Necesitamos solamente primitivas suficientes para capturar información estructurada:

```text
FormDefinition
FormSubmission
```

Una submission puede:

```text
identify/create Contact
        ↓
create/update Request
        ↓
emit Event
        ↓
resume Workflow
```

El builder visual, lógica condicional avanzada, themes y cientos de field types son extensiones futuras, no requisitos del core.

---

## 21. Conversations vs Requests

Una de las distinciones más importantes:

> **Conversation is context. Request is work.**

Chatwoot puede ser la fuente de verdad de una conversación. Request Engine debe ser la fuente de verdad del trabajo estructurado que resulta de ella.

Ejemplo:

```text
Chatwoot conversation #381
        │
        ├── Request req_A: quote plumbing repair
        │
        └── Request req_B: schedule technician visit
```

La conversación puede cerrarse y ambos requests seguir teniendo lifecycle propio.

---

## 22. Fulfillment

Un Request debe llegar a un resultado verificable, no solamente a un estado `completed` arbitrario.

Ejemplos:

```text
request_quote
    fulfillment → quoteId

book_consultation
    fulfillment → bookingId

request_callback
    fulfillment → callbackTaskId

emergency_service
    fulfillment → dispatchId / bookingId
```

El `fulfillment` crea la conexión entre intención y resultado real.

---

## 23. Ejemplos cross-industry

### QuisqueyaTech

```text
"Quiero una evaluación"
        ↓
Request: book_assessment
        ↓
Scheduling capability
        ↓
Booking
```

### Plomería

```text
"Se rompió una tubería"
        ↓
Request: emergency_service
        ↓
collect address / severity
        ↓
Scheduling or dispatch capability
        ↓
Technician visit
```

### Clínica dental

```text
"Necesito una limpieza"
        ↓
Request: book_cleaning
        ↓
Scheduling capability
        ↓
Booking
```

El core debe poder manejar los tres sin introducir condiciones como:

```text
if industry === "dental" ...
if industry === "plumbing" ...
```

Las diferencias deben vivir en `RequestType`, configuración, políticas y módulos de dominio.

---

## 24. Lo que V1 hizo bien y debe preservarse

Estas decisiones se consideran **aprendizaje validado del prototipo V1**:

1. multi-tenancy explícito;
2. public IDs separados de IDs internos;
3. UTC + IANA timezones;
4. idempotency keys;
5. revalidación transaccional antes de reservar capacidad;
6. snapshots de datos comerciales relevantes;
7. outbox / asynchronous side effects;
8. callbacks idempotentes y tipados;
9. audit trail separado de logs;
10. API keys con scopes, expiración y revocación;
11. external IDs como referencias y no identidad;
12. PII cifrada/blind-indexed cuando realmente sea necesaria;
13. agentes reciben tools deterministas en lugar de acceso libre a tablas;
14. el sistema de record interno no depende de Chatwoot, Evolution, n8n o LiveKit.

---

## 25. Lo que V1 debe dejar atrás

Estas decisiones no deben copiarse automáticamente a la siguiente versión:

1. modelar healthcare directamente en el core;
2. usar términos como `patientWarnedAboutAutoRelease` en primitivas universales;
3. mezclar scheduling, insurance, onboarding, provisioning, AI runtime y omnichannel en un solo dominio;
4. hacer de n8n una dependencia arquitectónica del engine;
5. hacer que Request Engine aprovisione Chatwoot/Evolution como responsabilidad principal;
6. permitir que un único archivo HTTP concentre routing, auth, parsing, crypto, callbacks y orchestration;
7. mantener OpenAPI manualmente separado de los schemas reales;
8. generar writes de availability para cada simple exploración de calendario;
9. construir decenas de tablas/endpoints antes de demostrar un vertical slice real;
10. confundir “reutilizable” con “soporta todas las industrias desde el día uno”.

---

## 26. Arquitectura de despliegue inicial

Preferencia: **modular monolith, API-first**.

No comenzar con una constelación de microservicios.

```text
Request Engine deployment
│
├── Core
│   ├── organizations
│   ├── contacts
│   ├── requests
│   ├── workflows
│   ├── events
│   ├── auth
│   └── audit
│
├── Modules
│   ├── scheduling
│   └── forms
│
└── API
```

Workers asíncronos pueden desplegarse por separado cuando exista una razón operacional real.

Los boundaries deben ser claros en el código antes de convertirse en boundaries de red.

---

## 27. Infraestructura aún no decidida

Este documento **no decide**:

- PostgreSQL vs Convex;
- lenguaje/framework exacto del API;
- queue/job runner;
- hosting;
- ORM;
- proveedor de auth;
- formato concreto del workflow runtime.

Cada una debe resolverse en un ADR después de evaluar requisitos y tradeoffs.

La tecnología debe servir al dominio, no redefinir el producto.

---

## 28. Vertical slice obligatorio de V2

Antes de añadir más módulos, V2 debe demostrar este camino completo:

```text
Organization
    ↓
Contact
    ↓
RequestType
    ↓
Request
    ↓
Workflow
    ↓
Scheduling availability
    ↓
Booking
    ↓
Domain event
    ↓
Webhook/outbox
    ↓
Fulfillment linked back to Request
```

Y debe funcionar para **dos organizaciones deliberadamente distintas**:

```text
1. QuisqueyaTech
2. Demo Plumbing
```

El objetivo no es demostrar muchas features. Es demostrar que la abstracción sobrevive a dos negocios diferentes sin contaminar el core con lógica vertical.

Después se puede añadir un tercer caso, por ejemplo una clínica dental, para verificar los límites del diseño.

---

## 29. Criterio para añadir una nueva feature

Antes de añadir algo al core, responder:

1. ¿Esta capacidad es necesaria para representar una solicitud o coordinar su lifecycle?
2. ¿Es común a múltiples industrias?
3. ¿Debe ser parte del system of record?
4. ¿Puede vivir como módulo o integración en vez de core?
5. ¿Tenemos un caso real que la necesita ahora?

Si las respuestas no justifican core, debe permanecer fuera.

---

## 30. North Star

Request Engine debe evolucionar hacia esto:

> **A headless, multi-tenant request orchestration engine that turns customer intent into deterministic business workflows and verifiable outcomes, independent of channel, AI provider, or vertical software.**

En español:

> **Un motor headless y multiempresa que transforma la intención de una persona o sistema en workflows de negocio deterministas y resultados verificables, independientemente del canal, proveedor de IA o software vertical.**

La frase que debe usarse para comprobar cualquier decisión futura sigue siendo la original:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Si una feature no ayuda a capturar la solicitud, determinar/ejecutar el workflow, producir el resultado o mantener su trazabilidad, probablemente no pertenece al núcleo de Request Engine.
