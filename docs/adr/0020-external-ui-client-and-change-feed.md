# 0020 — The user interface is an external client; the Jinja console retires at parity

Status: Accepted (2026-10-22), by explicit product-owner request. The change feed is
implemented by migration `0046_change_feed_signal`, `platform/changes/` and
`entrypoints/http/changes_stream.py`; evidence is listed below. The Jinja admin
console is not removed by this decision; it retires only at functional parity.

## Context

Request Engine is a headless API. The current human front-desk surface is a
server-rendered Jinja admin console (`entrypoints/http/admin_console/`) that runs in
the same deployment and reaches business owners through the same runtime API. The
product now has a dedicated user-interface application, `request-engine-app`
(`apps/web` browser client plus `apps/bff` backend-for-frontend), developed in its
own repository against the published OpenAPI contract.

Two problems follow:

1. Keeping two first-class UIs (Jinja console and the external app) doubles the
   presentation work and invites business rules to drift into whichever UI is
   easiest to change.
2. A front desk "Today" screen must reflect changes made by other staff (booking,
   check-in, call-next, service start/complete) within seconds. Polling every read
   every few seconds is expensive and still laggy; the API had no way to say
   "something you show has changed".

## Decision

1. **The user interface is an external client.** `request-engine-app` is the product
   UI. It consumes only the published runtime API (OpenAPI, capabilities, owner
   reads and semantic commands). It holds no business authority: every action is an
   owner operation authorized by the caller's ActorContext and capabilities.
2. **BFF holds tokens server-side.** The browser talks to the BFF with its own
   session cookie. The BFF holds the native session bearer token and calls the API
   server-to-server. The API therefore does not enable browser CORS and does not
   hand bearer tokens to browsers.
3. **The Jinja console remains until parity, then retires.** It is maintained for
   correctness but receives no new product surface. It is removed in a separate,
   explicit change once the external app covers its workflows.
4. **A change feed is an invalidation-only surface.** `GET /v1/changes/stream`
   (operationId `changes_stream`) is a Server-Sent Events stream that tells an
   authorized client that something it may display changed (`topic`, `kind`,
   `resource_type`, `resource_id`, `scope`, `occurred_at`). It never carries names,
   phones, notes, prices or any other personal or business payload; clients re-read
   through the normal owner reads, which re-apply authorization.
   - Topics are authorized with existing owner read capabilities
     (`day_board` → `appointments.day_board`, `queue` → `queue.staff_read`,
     `requests` → `requests.read_inbox`); an unauthorized requested topic is `403`
     (fail closed), never silently dropped. Authority is re-checked at most every
     60 s and the stream ends when it is lost.
   - Producer: a statement-level `AFTER INSERT` trigger on the outbox issues
     `pg_notify('request_engine_changes', '<organization_id>:<xid8>')`. NOTIFY is
     transactional, so only committed facts signal, in commit order.
   - Delivery: one dedicated autocommit LISTEN connection per runtime process wakes
     a reader that, per subscribed organization, reads the facts not visible in the
     last delivered `pg_snapshot` through the `security_invoker` view
     `request_read.change_feed_v1` under the tenant's RLS. Notifications only wake
     and order; a lost notification delays but never loses a fact.
   - Cursor: the SSE `id` is an opaque encoding of a `pg_snapshot` plus its issue
     time. Replay from `Last-Event-ID` returns every fact not visible in it. A
     sequence or the uuidv7 outbox id is not commit ordered and would let an
     "id > n" cursor skip a late-committing fact; a snapshot cannot. Replay window:
     900 s by default (`REQUEST_ENGINE_CHANGE_STREAM_REPLAY_WINDOW_SECONDS`); older or
     unknown cursors receive `reset` and the client refetches.
   - Back-pressure: per-stream bounded queue (slow consumer → queue dropped, one
     `reset`), per-principal concurrent limit (default 5,
     `REQUEST_ENGINE_CHANGE_STREAM_MAX_PER_PRINCIPAL`, `429`), a separate admission
     pool for streams in the HTTP request budget, `heartbeat` every 15 s.
   - Availability: LISTEN starts lazily on the first stream; the app starts and
     serves normally without it, and the stream answers `503
     change_feed_unavailable` until it connects. Clients fall back to polling.
   - Ownership: the mechanics are technical platform outbox/event plumbing
     (`platform/changes/`); the HTTP surface and the single fact→topic routing table
     are trust-boundary composition in `entrypoints/http/`. No module gains or loses
     authority; facts stay owned by booking, queue, delivery and requests.
   - Not tool-projected: a long-lived stream is a UI/BFF transport, not an owner
     operation an agent invokes; it has no `x-request-engine-tool-name`.

The consumer contract lives in `request-engine-app/docs/contracts/changes-stream.md`;
the producer's OpenAPI and this ADR are authoritative and the consumer file is
updated in the same change when they differ.

## Consequences

- Presentation work concentrates in one client. New front-desk surfaces are built in
  `request-engine-app`, not in Jinja.
- The API surface stays token-bearer and server-to-server; no CORS policy, cookie
  session or CSRF surface is added to the API.
- Outbox rows gain a nullable `change_xid xid8` column (defaulted for new rows) and
  an `AFTER INSERT` notify trigger. Outbox delivery semantics, statuses and claim
  functions are unchanged. NOTIFY's only commit-time failure mode is a full 8 GB
  notification queue, which requires a connected listener that stops draining.
- Every visible Today change is only as live as its outbox fact. Facts that do not
  append an outbox event do not signal. The original gap (walk-in `queue.join`,
  `queue.skip`, `queue.recall_hold`, `queue.release_recall_hold`) is closed by the
  queue owner: they append `queue.entry_joined.v1`, `queue.entry_skipped.v1`,
  `queue.entry_recall_held.v1` and `queue.entry_recall_released.v1` on the
  `QueueEntry` aggregate in the fact's transaction. The routing table needed no
  change (it routes by the `queue.` prefix and aggregate). The outbox worker
  dispatches internal handlers by exact type and publishes every other type
  unchanged, and the dev gateway sink accepts any type, so the new types need no
  consumer registration.
- Within one feed read, facts are ordered by notification (commit) order; replay
  after reconnect is ordered by fact creation, which equals commit order for
  non-overlapping transactions. Duplicates after reconnect are possible and clients
  must be idempotent, which an invalidation feed makes trivial.

Evidence: `tests/e2e/test_change_feed_stream.py` (real uvicorn server, real LISTEN,
PostgreSQL 18), `tests/db/test_change_feed_signal.py`,
`tests/unit/platform/changes/test_change_feed_hub.py`,
`tests/unit/test_change_feed_topics.py`,
`tests/e2e/test_change_feed_queue_triage_signals.py` (join/skip/recall-hold signals).

## Rejected alternatives

- **WebSocket.** Bidirectional channels are unnecessary for one-way invalidation,
  are harder to proxy, authenticate and rate-limit, and invite command traffic on a
  second execution path. SSE is plain HTTP with built-in reconnect and
  `Last-Event-ID`.
- **Polling only.** Simple but either laggy or expensive for every screen and
  tenant; it remains the documented fallback when the stream is unavailable.
- **CORS plus browser-held bearer tokens.** Exposes long-lived credentials to
  browser script and widens the API's trust boundary; the BFF keeps tokens
  server-side instead.
- **Data-carrying events.** Pushing row data would duplicate owner read models,
  bypass per-read authorization and party scoping, leak personal data to anything
  that can observe the stream, and create a second read contract to version. The
  feed says "re-read", nothing more.
- **Sequence or uuidv7 cursor.** Neither is commit ordered; a client could skip a
  fact committed after a later-numbered one. Rejected for the snapshot cursor.
- **Retiring the Jinja console immediately.** Would remove working front-desk flows
  before the external app covers them.
