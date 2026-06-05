import type { AuthConfig } from "convex/server"

export default {
  providers: [
    {
      domain: "https://factual-jackal-53.clerk.accounts.dev",
      applicationID: "convex",
    },
  ],
} satisfies AuthConfig
