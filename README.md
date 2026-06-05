# Request Engine

MVP base for a Chatwoot Dashboard App that turns conversations into actionable requests.

## Delivered

- Vite + React + TypeScript app shell.
- Tailwind CSS v4 styling and shadcn-compatible component setup.
- Clerk and Convex providers wired through environment variables.
- React Router routes for `/dashboard-app` and admin MVP pages.
- Convex schema for tenants, channels, AI state, catalog, knowledge, requests, events, appointments, quotes, integrations, and webhook events.
- Basic Convex queries/mutations for tenants, catalog, knowledge, and AI state.
- Chatwoot Dashboard App context hook using `postMessage`.
- Compact AI mode UI for `auto`, `manual`, `handoff`, and `paused`.

## Local Development

Install dependencies:

```bash
npm install
```

Start the frontend:

```bash
npm run dev
```

Build:

```bash
npm run build
```

Lint:

```bash
npm run lint
```

## Convex

Configure a Convex deployment before generating `_generated` files:

```bash
npx convex dev
```

Convex functions are under `convex/`. The frontend is intentionally able to build before a deployment is linked.

For Clerk auth, the React tree uses `ConvexProviderWithClerk` inside `ClerkProvider`.
The local `convex/auth.config.ts` points to the current Clerk issuer:

```txt
https://factual-jackal-53.clerk.accounts.dev
```

When moving to a shared cloud deployment, set the same issuer in the Convex dashboard as `CLERK_JWT_ISSUER_DOMAIN` and switch `auth.config.ts` back to reading that environment variable if desired.

## Environment

Create `.env.local` from `.env.example`. Public frontend values use the `VITE_` prefix. Chatwoot and provider tokens must stay in Convex environment variables, not in frontend code.
