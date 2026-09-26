# `platform_configuration`

This module owns installation-wide operational configuration lifecycle semantics.

It owns:

- typed configuration revisions;
- secret-binding metadata lifecycle;
- provider validation/test orchestration;
- platform configuration/readiness projections.

It does **not** own:

- secret-store transport mechanics (`request_engine.platform.secrets`);
- worker lease/fencing mechanics;
- SMTP delivery semantics (`communications`);
- Platform Owner authority (`tenancy`);
- OIDC cryptographic verification mechanics (`platform.security`).
