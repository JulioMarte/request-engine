# Delivery module

Owns admission, queue/waitlist state, service execution, and outcome evidence: AdmissionScope mapping, `QueueEntry`, `ServiceSession`, `Fulfillment`, and fulfillment corrections.

Initial commands include `CheckIn`, `JoinQueue`, `PromoteWaitlistEntry`, `StartServiceSession`, `CompleteServiceSession`, `RecordFulfillment`, and `CorrectFulfillment`.

Execution is not fulfillment, and fulfillment is not request completion. Cross-module coordination with booking and requests must preserve the shared serialization rules.
