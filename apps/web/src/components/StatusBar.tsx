"use client"

import { type Status } from "@/lib/api"

type Phase = "pending" | "up" | "down"

export function StatusBar({ status, phase }: { status: Status | null; phase: Phase }) {
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
