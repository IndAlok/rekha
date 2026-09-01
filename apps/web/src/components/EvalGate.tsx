"use client"

import { useState } from "react"
import { ApiError, api } from "@/lib/api"
import { Banner } from "./ui/Banner"
import { Button } from "./ui/Button"
import { EmptyState } from "./ui/EmptyState"
import { Panel } from "./ui/Panel"

export function EvalGate({
  error,
  onReady,
}: {
  error: unknown
  onReady: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [local, setLocal] = useState<string | null>(null)
  const code = error instanceof ApiError ? error.code : "HTTP_ERROR"
  const message = error instanceof Error ? error.message : String(error)

  async function run() {
    setBusy(true)
    setLocal(null)
    try {
      await api.runEval(42)
      onReady()
    } catch (err) {
      setLocal(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (code === "UNAUTHORIZED") {
    return (
      <Panel title="Ops token required">
        <EmptyState title="This call needs X-Ops-Token">
          Outside REKHA_ENV=dev, mutating routes need the token. Paste it on Status, then retry.
        </EmptyState>
        <Banner kind="danger">{message}</Banner>
      </Panel>
    )
  }

  if (code === "API_UNREACHABLE") {
    return (
      <Panel title="API is down">
        <EmptyState title="Nothing to load">
          This page talks to the API through /api on the same host. Start it with make api, or run both sides with make serve.
        </EmptyState>
        <p className="bad">{message}</p>
      </Panel>
    )
  }

  if (code === "CASE_NOT_FOUND") {
    return (
      <Panel title="Case not found">
        <p className="lede">That id is not in the last eval batch or the live store.</p>
        <Banner kind="warn">{message}</Banner>
      </Panel>
    )
  }

  if (code === "EVAL_MISSING" || code === "EVAL_BROKEN") {
    return (
      <Panel title="No eval report yet">
        <p className="lede">The API builds the batch on first boot. If you still see this, run it here. A few seconds. No keys needed.</p>
        <Banner kind="warn">{message}</Banner>
        <Button variant="primary" disabled={busy} onClick={run}>
          {busy ? "Running eval..." : "Run eval"}
        </Button>
        {local && <p className="bad">{local}</p>}
      </Panel>
    )
  }

  return (
    <Panel title="Could not load this page">
      <p className="lede">Reload, or open Status and run eval again.</p>
      <Banner kind="warn">{message}</Banner>
      <Button variant="primary" disabled={busy} onClick={run}>
        {busy ? "Running eval..." : "Run eval"}
      </Button>
      {local && <p className="bad">{local}</p>}
    </Panel>
  )
}
