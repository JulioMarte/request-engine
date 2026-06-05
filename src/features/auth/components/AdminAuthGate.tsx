import { ClerkLoaded, ClerkLoading, SignIn } from "@clerk/clerk-react"
import { Bot, CalendarCheck, FileText, LockKeyhole, MessageSquareText } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { config } from "@/app/config"
import { APP_NAME } from "@/lib/constants"

export function AppSignInGate() {
  if (!config.clerkPublishableKey) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-10">
        <Card className="max-w-md">
          <CardHeader>
            <CardTitle>Authentication is not configured</CardTitle>
            <CardDescription>Set VITE_CLERK_PUBLISHABLE_KEY before using this application.</CardDescription>
          </CardHeader>
        </Card>
      </main>
    )
  }

  return <AppSignInPage />
}

function AppSignInPage() {
  return (
    <main className="min-h-screen bg-[linear-gradient(180deg,#f7f8fa_0%,#eef4f3_48%,#f7f8fa_100%)]">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_430px] lg:items-center lg:px-6">
        <section className="flex flex-col justify-center">
          <div className="mb-10 inline-flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="text-sm font-semibold">{APP_NAME}</p>
              <p className="text-xs text-muted-foreground">Secure access</p>
            </div>
          </div>

          <div className="max-w-2xl">
            <p className="mb-3 text-sm font-medium text-primary">Operations access</p>
            <h1 className="text-3xl font-semibold leading-tight text-foreground sm:text-4xl">
              Control conversational requests before they touch your operation.
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground">
              Only approved operators can access tenants, Chatwoot channels, catalog data, knowledge entries, and provider settings.
            </p>
          </div>

          <div className="mt-8 grid max-w-2xl gap-3 sm:grid-cols-2">
            <LoginSignal icon={MessageSquareText} title="Chatwoot context" description="Map accounts, inboxes, contacts, and conversations." />
            <LoginSignal icon={CalendarCheck} title="Request workflows" description="Prepare appointments, quotes, handoffs, and AI states." />
            <LoginSignal icon={FileText} title="Business knowledge" description="Keep reusable service and FAQ data organized by tenant." />
            <LoginSignal icon={LockKeyhole} title="Protected application" description="Every internal route stays hidden until Clerk confirms the session." />
          </div>
        </section>

        <section className="flex items-center justify-center lg:justify-end">
          <Card className="w-full max-w-[430px] border bg-card/95 shadow-xl">
            <CardHeader className="pb-4">
              <CardTitle className="text-lg">Sign in</CardTitle>
              <CardDescription>Use an approved operator account to continue.</CardDescription>
            </CardHeader>
            <CardContent>
              <ClerkLoading>
                <div className="space-y-3">
                  <div className="h-10 animate-pulse rounded-md bg-muted" />
                  <div className="h-10 animate-pulse rounded-md bg-muted" />
                  <div className="h-10 animate-pulse rounded-md bg-muted" />
                </div>
              </ClerkLoading>
              <ClerkLoaded>
              <SignIn
                  appearance={{
                    elements: {
                      rootBox: "w-full",
                      cardBox: "w-full shadow-none",
                      card: "w-full border-0 bg-transparent p-0 shadow-none",
                      headerTitle: "hidden",
                      headerSubtitle: "hidden",
                      socialButtonsBlockButton: "rounded-md border-border",
                      formButtonPrimary: "bg-primary hover:bg-primary/90",
                      footer: "hidden",
                      footerAction: "hidden",
                      footerActionText: "hidden",
                      footerActionLink: "hidden",
                    },
                  }}
                  fallbackRedirectUrl="/admin"
                  forceRedirectUrl="/admin"
                  routing="hash"
                />
              </ClerkLoaded>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  )
}

function LoginSignal({
  description,
  icon: Icon,
  title,
}: {
  description: string
  icon: typeof Bot
  title: string
}) {
  return (
    <div className="rounded-lg border bg-card/80 p-4">
      <Icon className="mb-3 h-5 w-5 text-primary" aria-hidden="true" />
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
    </div>
  )
}
