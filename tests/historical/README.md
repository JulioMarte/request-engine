# Historical test evidence

This directory contains tests whose primary question is historical/release provenance rather than current product architecture.

A historical test answers questions such as:

```text
What exactly did V3 freeze/release prove?
Is the pinned release evidence internally coherent and reproducible?
Does a deliberately retained compatibility path still work against the pinned release baseline?
```

It must not answer a different question by accident:

```text
What is current Request Engine allowed to become?
```

Rules:

- Historical tests are automatically marked `historical` by this directory's `conftest.py`.
- Keep release hashes, exact inventories, frozen fingerprints and artifact semantics here when exactness is the point of the evidence.
- Do not move a live safety invariant here merely because it was first implemented during V3. Tenant isolation, capacity ownership, idempotency, crash/retry safety, authority and similar guarantees remain current-product proofs when the guarantee is still accepted.
- Current-product CI may evolve independently of historical structure. The historical lane is responsible for running these proofs when V3 provenance/compatibility is relevant.
