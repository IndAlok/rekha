"use client"

import { useEffect, useState } from "react"
import { api, type Status } from "@/lib/api"

type Phase = "pending" | "up" | "down"

export function StatusBar() {
  const [phase, setPhase] = useState<Phase>("pending")
  const [status, setStatus] = useState<Status | null>(null)

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      if (document.hidden) return
      api
        .status()
        .then((row) => {
          if (cancelled) return
          setStatus(row)
          setPhase("up")
        })
        .catch(() => {
          if (cancelled) return
          setStatus(null)
          setPhase("down")
        })
    }
    tick()
    const id = setInterval(tick, 8000)
    const vis = () => {
      if (!document.hidden) tick()
    }
    document.addEventListener("visibilitychange", vis)
    return () => {
      cancelled = true
      clearInterval(id)
      document.removeEventListener("visibilitychange", vis)
    }
  }, [])

  const evalUp = Boolean(status?.eval_ready)
  return (
    <span className="btn-row">
      <span className={`pill ${phase === "up" ? "on" : phase === "down" ? "down" : ""}`}>
        API {phase === "pending" ? "..." : phase}
      </span>
      <span className={`pill ${evalUp ? "on" : phase === "pending" ? "" : "off"}`}>
        eval {phase === "pending" ? "..." : evalUp ? "ready" : "empty"}
      </span>
    </span>
  )
}
