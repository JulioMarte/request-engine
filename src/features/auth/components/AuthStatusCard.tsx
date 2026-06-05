import { SignInButton, SignedIn, SignedOut, UserButton } from "@clerk/clerk-react"
import { Authenticated, AuthLoading, Unauthenticated, useConvexAuth } from "convex/react"
import { ShieldCheck, ShieldQuestion } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { config } from "@/app/config"

function ConvexAuthState() {
  const auth = useConvexAuth()

  return (
    <div className="rounded-md bg-muted p-3 text-xs">
      <p>Convex auth loading: {auth.isLoading ? "yes" : "no"}</p>
      <p>Convex authenticated: {auth.isAuthenticated ? "yes" : "no"}</p>
    </div>
  )
}

export function AuthStatusCard() {
  const hasClerk = Boolean(config.clerkPublishableKey)
  const hasConvex = Boolean(config.convexUrl)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auth Status</CardTitle>
        <CardDescription>Clerk session and Convex token bridge.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            {hasClerk ? <ShieldCheck className="h-4 w-4" /> : <ShieldQuestion className="h-4 w-4" />}
            Clerk publishable key
          </span>
          <span className="font-medium">{hasClerk ? "configured" : "missing"}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            {hasConvex ? <ShieldCheck className="h-4 w-4" /> : <ShieldQuestion className="h-4 w-4" />}
            Convex URL
          </span>
          <span className="font-medium">{hasConvex ? "configured" : "missing"}</span>
        </div>

        {hasClerk ? (
          <>
            <SignedOut>
              <SignInButton mode="modal">
                <Button size="sm">Sign in</Button>
              </SignInButton>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center justify-between rounded-md bg-muted p-3">
                <span>Clerk session active</span>
                <UserButton />
              </div>
            </SignedIn>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Set VITE_CLERK_PUBLISHABLE_KEY to enable Clerk.</p>
        )}

        {hasConvex && hasClerk ? (
          <>
            <AuthLoading>
              <p className="text-xs text-muted-foreground">Convex is checking the Clerk token.</p>
            </AuthLoading>
            <Authenticated>
              <p className="text-xs font-medium text-primary">Convex accepted the Clerk session.</p>
            </Authenticated>
            <Unauthenticated>
              <p className="text-xs text-muted-foreground">Sign in to send a Clerk token to Convex.</p>
            </Unauthenticated>
            <ConvexAuthState />
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Add VITE_CONVEX_URL to enable authenticated Convex calls from the browser.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
