import { NavLink, Outlet } from "react-router-dom"
import { ClerkLoaded, ClerkLoading, SignedIn, SignedOut, UserButton } from "@clerk/clerk-react"
import { Bot, Boxes, Brain, CalendarDays, Home, LayoutDashboard, Plug, Settings, UsersRound } from "lucide-react"
import { config } from "@/app/config"
import { AppSignInGate } from "@/features/auth/components/AdminAuthGate"
import { APP_NAME } from "@/lib/constants"

const links = [
  { to: "/operations", label: "Operación", icon: LayoutDashboard },
  { to: "/operations/bookings", label: "Agenda", icon: CalendarDays },
  { to: "/operations/queue", label: "Cola", icon: UsersRound },
  { to: "/operations/agents", label: "Agentes", icon: Bot },
  { to: "/admin/tenants", label: "Empresas", icon: Home },
  { to: "/admin/catalog", label: "Servicios", icon: Boxes },
  { to: "/admin/knowledge", label: "Prompts", icon: Brain },
  { to: "/admin/integrations", label: "Conexiones", icon: Plug },
  { to: "/admin", label: "Configuración", icon: Settings },
]

export function AppShell() {
  if (!config.clerkPublishableKey) {
    return <AppSignInGate />
  }

  return (
    <>
      <ClerkLoading>
        <main className="flex min-h-screen items-center justify-center bg-background px-4">
          <div className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm">
            <div className="mb-4 h-10 w-10 animate-pulse rounded-lg bg-muted" />
            <div className="h-4 w-40 animate-pulse rounded bg-muted" />
            <div className="mt-3 h-3 w-56 animate-pulse rounded bg-muted" />
          </div>
        </main>
      </ClerkLoading>
      <ClerkLoaded>
        <SignedOut>
          <AppSignInGate />
        </SignedOut>
        <SignedIn>
          <div className="min-h-screen">
            <AuthenticatedHeader />
            <Outlet />
          </div>
        </SignedIn>
      </ClerkLoaded>
    </>
  )
}

function AuthenticatedHeader() {
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
        <div>
          <p className="text-sm font-semibold">{APP_NAME}</p>
          <p className="text-xs text-muted-foreground">Agenda autónoma y colas</p>
        </div>
        <div className="flex items-center gap-3">
          <nav className="hidden items-center gap-1 md:flex" aria-label="Navegacion principal">
            {links.map((link) => (
              <NavLink
                className={({ isActive }) =>
                  `inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium ${
                    isActive ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted"
                  }`
                }
                key={link.to}
                to={link.to}
              >
                <link.icon className="h-4 w-4" aria-hidden="true" />
                {link.label}
              </NavLink>
            ))}
          </nav>
          {config.clerkPublishableKey && <UserButton />}
        </div>
      </div>
      <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-3 sm:px-6 md:hidden" aria-label="Navegacion movil">
        {links.map((link) => (
          <NavLink
            className={({ isActive }) =>
              `inline-flex min-h-10 shrink-0 items-center gap-2 rounded-md px-3 text-xs font-medium ${
                isActive ? "bg-muted text-foreground" : "text-muted-foreground"
              }`
            }
            key={link.to}
            to={link.to}
          >
            <link.icon className="h-4 w-4" aria-hidden="true" />
            {link.label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}
