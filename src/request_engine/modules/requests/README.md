# Requests module

Owns durable request intent: `Request`, participants/targets/correlations, `OfferingSelection`, `OutcomeScope`, workflow key/version, and request completion coordination.

Initial commands include `CreateRequest`, `AddRequestParticipant`, `SelectOffering`, `UpdateOfferingSelectionBeforeCommitment`, and `CompleteRequest`.

Owns `request_read.request_summary_v1` query semantics.

`OutcomeScope` is the stable requested-outcome serialization identity. Delivery owns Fulfillment facts applied to it, so fulfillment commands coordinate through this module's public contract while preserving the documented lock protocol.
