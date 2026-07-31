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
        <CardTitle>Estado de autenticacion</CardTitle>
        <CardDescription>Sesion Clerk y puente de token hacia Convex.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            {hasClerk ? <ShieldCheck className="h-4 w-4" /> : <ShieldQuestion className="h-4 w-4" />}
            Clerk publishable key
          </span>
          <span className="font-medium">{hasClerk ? "configurado" : "faltante"}</span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            {hasConvex ? <ShieldCheck className="h-4 w-4" /> : <ShieldQuestion className="h-4 w-4" />}
            Convex URL
          </span>
          <span className="font-medium">{hasConvex ? "configurado" : "faltante"}</span>
        </div>

        {hasClerk ? (
          <>
            <SignedOut>
              <SignInButton mode="modal">
                <Button size="sm">Iniciar sesion</Button>
              </SignInButton>
            </SignedOut>
            <SignedIn>
              <div className="flex items-center justify-between rounded-md bg-muted p-3">
                <span>Sesion Clerk activa</span>
                <UserButton />
              </div>
            </SignedIn>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Define VITE_CLERK_PUBLISHABLE_KEY para habilitar Clerk.</p>
        )}

        {hasConvex && hasClerk ? (
          <>
            <AuthLoading>
              <p className="text-xs text-muted-foreground">Convex esta revisando el token de Clerk.</p>
            </AuthLoading>
            <Authenticated>
              <p className="text-xs font-medium text-primary">Convex acepto la sesion de Clerk.</p>
            </Authenticated>
            <Unauthenticated>
              <p className="text-xs text-muted-foreground">Inicia sesion para enviar un token de Clerk a Convex.</p>
            </Unauthenticated>
            <ConvexAuthState />
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Agrega VITE_CONVEX_URL para habilitar llamadas autenticadas a Convex desde el navegador.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
