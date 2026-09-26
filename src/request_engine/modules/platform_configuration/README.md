# Platform Configuration

Owns installation-wide operational configuration lifecycle and administrative projections.

This module owns typed configuration revision semantics, stage/validate/activate/disable commands,
secret-binding metadata lifecycle, provider validation/test orchestration, and platform readiness
projections.

It does **not** own secret-store transport mechanics, worker mechanics, SMTP delivery semantics,
identity/Platform Owner authority, OIDC cryptographic verification, or business communication
intent. Those remain in their existing owners.

Plaintext secrets must never cross this module's human-facing read contracts.
