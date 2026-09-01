"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { Field } from "@/components/ui/Field"
import { JsonView } from "@/components/ui/JsonView"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { api, type InboxRow } from "@/lib/api"
import { ago } from "@/lib/format"

const SAMPLES = [
  { id: "payment_failed", label: "failed" },
  { id: "payment_authorized", label: "authorized" },
  { id: "cart_abandoned", label: "cart" },
  { id: "subscription_halted", label: "subscription" },
] as const

type Sample = (typeof SAMPLES)[number]["id"]

export default function WebhooksPage() {
  const [sample, setSample] = useState<Sample>("payment_failed")
  const [body, setBody] = useState("")
  const [eventId, setEventId] = useState("")
  const [signature, setSignature] = useState("")
  const [lastId, setLastId] = useState<string | null>(null)
  const [out, setOut] = useState<unknown>(null)
  const [err, setErr] = useState<string | null>(null)
  const [recent, setRecent] = useState<InboxRow[]>([])
  const [busy, setBusy] = useState(false)

  const loadSample = (name: Sample) => {
    setSample(name)
    api
      .sampleWebhook(name)
      .then((s) => setBody(JSON.stringify(s, null, 2)))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }

  const refreshRecent = () => {
    api
      .recentWebhooks(15)
      .then((r) => setRecent(r.rows))
      .catch(() => setRecent([]))
  }

  useEffect(() => {
    loadSample("payment_failed")
    refreshRecent()
    const id = setInterval(() => {
      if (!document.hidden) refreshRecent()
    }, 8000)
    return () => clearInterval(id)
  }, [])

  const send = async (id: string) => {
    let payload: unknown
    try {
      payload = JSON.parse(body)
    } catch {
      setErr("Body is not valid JSON")
      return
    }
    setBusy(true)
    try {
      const r = await api.webhook(payload, id, signature.trim() || undefined)
      setOut(r)
      setErr(null)
      setLastId(id)
      refreshRecent()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const result = out && typeof out === "object" ? (out as Record<string, unknown>) : null
  const inner = result && typeof result.result === "object" && result.result ? (result.result as Record<string, unknown>) : null
  const verdict = inner && typeof inner.verdict === "object" && inner.verdict ? (inner.verdict as Record<string, unknown>) : null

  return (
    <>
      <PageHeader
        title="Webhook console"
        lede="Prod rejects unsigned bodies. Save the ops token on Status, then Send signs the JSON with the webhook secret. Razorpay's own test button signs itself. Replay uses the same event id."
      />
      {err ? <Banner kind="danger">{err}</Banner> : null}
      {result?.deduped ? <Banner kind="ok">deduped true. Same event id, no second case.</Banner> : null}
      <div className="cols">
        <Panel
          title="Request"
          actions={
            <SegmentedControl
              ariaLabel="Sample fixture"
              value={sample}
              onChange={loadSample}
              options={SAMPLES.map((s) => ({ id: s.id, label: s.label }))}
            />
          }
        >
          <Field label="Event id">
            <input className="input mono" value={eventId} onChange={(e) => setEventId(e.target.value)} placeholder="leave blank to mint one" />
          </Field>
          <Field label="X-Razorpay-Signature">
            <input
              className="input mono"
              value={signature}
              onChange={(e) => setSignature(e.target.value)}
              placeholder="blank: sign with ops token"
            />
          </Field>
          <textarea className="textarea" aria-label="Webhook JSON body" value={body} onChange={(e) => setBody(e.target.value)} rows={16} style={{ marginTop: 10 }} />
          <div className="btn-row" style={{ marginTop: 12 }}>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => {
                const id = eventId.trim() || `sim-${Date.now()}`
                setEventId(id)
                void send(id)
              }}
            >
              {busy ? "Sending..." : "Send"}
            </Button>
            <Button disabled={!lastId || busy} onClick={() => lastId && void send(lastId)} title="Resend the exact same event id">
              Replay same event id
            </Button>
          </div>
        </Panel>
        <div className="stack">
          <Panel title="Response">
            {verdict?.effect ? (
              <p>
                <Badge>{String(verdict.effect)}</Badge> {String(verdict.reason_code || "")}
              </p>
            ) : null}
            {out ? <JsonView value={out} label="response" /> : <p className="muted">Send a fixture to see the verdict.</p>}
          </Panel>
          <Panel title="Recent events" lede="Inbox rows. Replay proof is the same id twice.">
            {recent.length === 0 ? <p className="muted">Empty. Send one.</p> : null}
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {recent.map((r) => (
                <li key={r.event_id} style={{ display: "flex", gap: 8, padding: "6px 0", borderBottom: "1px solid var(--line)", fontSize: 12, flexWrap: "wrap" }}>
                  <span className="mono">{r.event_id}</span>
                  <span className="muted">{r.event_type}</span>
                  <span className="muted">{r.processed ? "yes" : "."}</span>
                  <span className="faint">{ago(r.received_at)}</span>
                  {r.error_text ? <span className="bad">{r.error_text}</span> : null}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  )
}
