# Tenancy module

Owns `Organization`, `Principal`, `Party`, and `Representation` semantics and local authority materialization.

Primary concerns: hard tenant boundary, authority snapshots/revocation coordination, actor/party distinction, and exact policy/representation provenance.

Other modules consume only public tenancy contracts; participant roles or external correlations never become authorization by implication.

## Party registry (S0b)

Owns `parties.register`, `parties.add_contact_point`, `parties.confirm_contact_point`,
the operator-granted corrections (`parties.rename`, `parties.add_document`,
`parties.deactivate_contact_point`, `parties.deactivate`) and `parties.lookup`
(contract: `docs/v3/38-s0b-party-registry-contract.md`). A Party is
identity-only — never a CRM profile. Contact-point verification is operator-asserted:
creation by an operator principal is verified, by a bot principal is not, and only the
confirm command flips it upward (DB guard rejects downward flips). `registered_via` is
derived server-side from the caller's authority, never client-sent. Phone lookup is
multi-match by design (shared family numbers). Identity documents (cédula/passport) are
unique per tenant, kind and normalized value. Correction capabilities are grant-gated
operator-only; bots hold only register/add_contact_point/lookup, and bot-created
Parties get a "WhatsApp <number>" placeholder name corrected via `parties.rename`.
