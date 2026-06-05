export const config = {
  convexUrl: import.meta.env.VITE_CONVEX_URL as string | undefined,
  clerkPublishableKey: import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined,
  appEnv: (import.meta.env.APP_ENV as string | undefined) ?? "development",
}
