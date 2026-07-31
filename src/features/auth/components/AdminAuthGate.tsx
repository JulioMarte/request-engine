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
            <CardTitle>Autenticacion no configurada</CardTitle>
            <CardDescription>Define VITE_CLERK_PUBLISHABLE_KEY antes de usar esta aplicacion.</CardDescription>
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
            <p className="text-xs text-muted-foreground">Acceso seguro</p>
            </div>
          </div>

          <div className="max-w-2xl">
            <p className="mb-3 text-sm font-medium text-primary">Acceso operativo</p>
            <h1 className="text-3xl font-semibold leading-tight text-foreground sm:text-4xl">
              Controla solicitudes conversacionales antes de que impacten la operacion.
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground">
              Solo operadores aprobados pueden acceder a tenants, canales de Chatwoot, catalogo, conocimiento y proveedores.
            </p>
          </div>

          <div className="mt-8 grid max-w-2xl gap-3 sm:grid-cols-2">
            <LoginSignal icon={MessageSquareText} title="Contexto Chatwoot" description="Mapea cuentas, inboxes, contactos y conversaciones." />
            <LoginSignal icon={CalendarCheck} title="Flujos de solicitud" description="Prepara citas, cotizaciones, derivaciones y estados de IA." />
            <LoginSignal icon={FileText} title="Conocimiento" description="Organiza servicios y preguntas frecuentes por tenant." />
            <LoginSignal icon={LockKeyhole} title="App protegida" description="Las rutas internas quedan ocultas hasta que Clerk confirme la sesion." />
          </div>
        </section>

        <section className="flex items-center justify-center lg:justify-end">
          <Card className="w-full max-w-[430px] border bg-card/95 shadow-xl">
            <CardHeader className="pb-4">
              <CardTitle className="text-lg">Iniciar sesion</CardTitle>
              <CardDescription>Usa una cuenta de operador aprobada para continuar.</CardDescription>
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
