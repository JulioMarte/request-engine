# Development Guide

Start the frontend:

```bash
npm run dev
```

Generate Convex types and run the Convex dev server after configuring Convex:

```bash
npx convex dev
```

Set public frontend values in `.env.local` using `.env.example` as a reference. Keep Chatwoot and provider secrets in Convex environment variables.

## Auth Check

Admin routes are protected by Clerk. Open `/admin`; signed-out users should see a `Sign in required` card. After signing in, the Admin home page shows `Auth Status`, including whether the Convex URL is configured and whether Convex has accepted the Clerk session.

For Convex + Clerk, the provider order matters:

1. `ClerkProvider`
2. `ConvexProviderWithClerk`
3. App routes
