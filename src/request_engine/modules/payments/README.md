# Payments module

Owns pricing and financial truth needed by Request Engine: `PriceDetermination`, `PaymentRequirement`, `PaymentTransaction`, financial observations/corrections/reversals, allocations/adjustments, refunds, disputes, and reconciliation.

Provider payloads are normalized into typed financial facts; they never directly mutate generic payment status. External truth is recorded even when it creates a local reconciliation problem.

Owns payment read contracts and payment-provider integrations. Request Engine does not become a universal ledger, PSP, tax engine, or bank.
