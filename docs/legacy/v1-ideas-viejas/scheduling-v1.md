# [HISTÓRICO V1] Arquitectura de agenda v1

> Este documento describe decisiones de la implementación V1 basada en Convex. Se conserva únicamente como referencia histórica. No es arquitectura autoritativa para V2. Las lecciones que siguen vigentes fueron sintetizadas en `../02-v1-lessons-preserved.md`.

## Invariantes

- Todos los timestamps persistidos son epoch UTC; toda entidad operativa conserva una zona IANA.
- Una oferta de disponibilidad expira en cinco minutos, es de un solo uso y no garantiza capacidad hasta que `booking.create` termina.
- La lectura de conflictos, la reserva de capacidad, las asignaciones y el consumo de la oferta ocurren en una mutación Convex serializable.
- `pending_confirmation` consume capacidad.
- Una acción externa nunca modifica estado sin un callback idempotente y tipado.
- El ticket de una cola se asigna únicamente durante check-in. Antes de ese momento solo puede mostrarse una estimación con disclaimer.
- La prioridad de cola requiere principal, motivo y auditoría.
- IDs de Chatwoot, Evolution o n8n son referencias externas; nunca son la identidad pública de una entidad.

## Límites de datos

Convex guarda identidad estructurada, cobertura, estados, referencias y auditoría. Chatwoot guarda conversación y adjuntos. Request Engine no contiene expediente clínico, reclamaciones ARS ni transcripciones como autoridad.

Documento de identidad, número de afiliación y credenciales profesionales se almacenan como:

- ciphertext AES-GCM;
- hash ciego HMAC para igualdad/búsqueda;
- versión enmascarada para UI;
- versión de llave para rotación.

La historia clínica y el texto libre sensible quedan fuera de webhooks generales. Las rutas de PII requieren scopes independientes.

## Confirmación

La política inicial crea intentos T-72 por WhatsApp, T-48 por correo/canal alternativo y T-30 por voz. La liberación T-24 solo se ejecuta cuando el servicio la permite, el usuario fue advertido, hubo al menos una entrega y se intentó otro canal. `never_auto_cancel` siempre gana.

Mensajería y llamadas deben ser despachadas por el adaptador en ventanas locales 09:00–20:00 y 09:00–19:00. Los reintentos viven en el outbox y nunca dentro de la mutación de reserva.

## Integraciones

Chatwoot se aprovisiona mediante una Platform App. La cuenta corresponde a una organización y el Agent Bot apunta inicialmente a n8n. Evolution Baileys es solo para pilotos; el paso a Meta Cloud API es una puerta de producción para clientes médicos pagados.

Evolution permite crear la instancia Baileys con `/instance/create`, QR habilitado y datos Chatwoot, o configurar una existente con `/chatwoot/set/{instance}` y `autoCreate`. Cada paso debe persistir `externalId`, estado, intento e idempotency key antes de avanzar.

Los callbacks de n8n/LiveKit/FusionPBX firman `timestamp.body` con HMAC SHA-256 y solo aceptan intenciones `confirm`, `cancel`, `reprogram` o `unknown`. Una transcripción libre jamás cambia una cita.

## Feriados

Cada ocurrencia conserva país, subdivisión, fecha observada, fuente y estado de revisión. Siete días antes se solicita una decisión al encargado. La ausencia de respuesta conserva el horario: nunca produce un cierre automático. Cambiar el horario y actuar sobre citas afectadas son operaciones separadas.

Fuentes iniciales:

- República Dominicana: Ministerio de Trabajo/Presidencia.
- Estados Unidos: Office of Personnel Management para feriados federales.

## Migración

1. Ejecutar v1 en paralelo con las tablas heredadas.
2. Importar organizaciones, personas y catálogo con IDs externos como mappings.
3. Comparar conteos, snapshots y reservas por fecha.
4. Cambiar lecturas del panel y de agentes a v1.
5. Congelar escrituras heredadas.
6. Exportar respaldo y eliminar tablas únicamente en una migración posterior aprobada.
