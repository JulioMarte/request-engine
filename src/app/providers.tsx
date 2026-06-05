import type { ReactNode } from "react"
import { ClerkProvider, useAuth } from "@clerk/clerk-react"
import { ConvexProvider, ConvexReactClient } from "convex/react"
import { ConvexProviderWithClerk } from "convex/react-clerk"
import { config } from "@/app/config"

const convex = config.convexUrl ? new ConvexReactClient(config.convexUrl) : null

export function AppProviders({ children }: { children: ReactNode }) {
  if (config.clerkPublishableKey && convex) {
    return (
      <ClerkProvider publishableKey={config.clerkPublishableKey}>
        <ConvexProviderWithClerk client={convex} useAuth={useAuth}>
          {children}
        </ConvexProviderWithClerk>
      </ClerkProvider>
    )
  }

  if (convex) {
    return <ConvexProvider client={convex}>{children}</ConvexProvider>
  }

  if (config.clerkPublishableKey) {
    return <ClerkProvider publishableKey={config.clerkPublishableKey}>{children}</ClerkProvider>
  }

  return children
}
