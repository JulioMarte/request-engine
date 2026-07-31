import * as React from "react"
import { cn } from "@/lib/utils"

type BadgeVariant = "default" | "secondary" | "outline" | "warning" | "success" | "neutral"

const variants: Record<BadgeVariant, string> = {
  default: "bg-primary text-primary-foreground",
  secondary: "bg-secondary text-secondary-foreground",
  outline: "border bg-card text-foreground",
  warning: "bg-amber-100 text-amber-900",
  success: "bg-emerald-100 text-emerald-900",
  neutral: "bg-muted text-muted-foreground",
}

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium", variants[variant], className)}
      {...props}
    />
  )
}
