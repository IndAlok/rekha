"use client"

import { useEffect, useState } from "react"
import { Button } from "./Button"

export function ConfirmButton({
  children,
  confirmLabel = "Confirm",
  onConfirm,
  busy,
  variant = "secondary",
  danger,
}: {
  children: React.ReactNode
  confirmLabel?: string
  onConfirm: () => void | Promise<void>
  busy?: boolean
  variant?: "primary" | "secondary" | "ghost" | "danger"
  danger?: boolean
}) {
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setArmed(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [armed])

  if (!armed) {
    return (
      <Button variant={danger ? "danger" : variant} disabled={busy} onClick={() => setArmed(true)}>
        {children}
      </Button>
    )
  }
  return (
    <span className="btn-row">
      <Button
        variant={danger ? "danger" : "primary"}
        disabled={busy}
        onClick={async () => {
          try {
            await onConfirm()
          } catch {
            /* caller toasts */
          } finally {
            setArmed(false)
          }
        }}
      >
        {confirmLabel}
      </Button>
      <Button variant="ghost" disabled={busy} onClick={() => setArmed(false)}>
        Cancel
      </Button>
    </span>
  )
}
