# Request Engine Architecture

Request Engine separates Chatwoot conversation ownership from operational request state.

- Chatwoot owns messages, contacts, labels, inboxes, and conversation status.
- Convex owns tenants, channels, AI state, catalog, knowledge, requests, and technical events.
- The Dashboard App receives Chatwoot context with `postMessage`, but that context is not authentication.
- External providers run through Convex actions and provider adapters.

The first MVP pass includes the Vite app shell, admin routes, Dashboard App context, AI mode controls, and the Convex schema/functions needed by deliverables 1 through 4.
