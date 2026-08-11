# Tenancy module

Owns `Organization`, `Principal`, `Party`, and `Representation` semantics and local authority materialization.

Primary concerns: hard tenant boundary, authority snapshots/revocation coordination, actor/party distinction, and exact policy/representation provenance.

Other modules consume only public tenancy contracts; participant roles or external correlations never become authorization by implication.
