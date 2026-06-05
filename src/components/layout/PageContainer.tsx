import type { ReactNode } from "react"

export function PageContainer({ children }: { children: ReactNode }) {
  return <main className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">{children}</main>
}
