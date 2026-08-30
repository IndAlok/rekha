"use client"

import Link from "next/link"
import { useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { JsonView } from "@/components/ui/JsonView"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { api, type CaseRow } from "@/lib/api"
import { inr } from "@/lib/format"

const BASE = {
  customer_id: "cust-run",
  merchant_id: "merch_d2c",
  merchant_name: "NoonCart",
  first_name: "Riya",
  loss_class: "payment_failure",
  amount_paise: 129900,
  currency: "INR",
  error_reason: "insufficient_funds",
  error_source: "customer",
  consent_status: "GRANTED",
  suppressed: false,
  legal_hold: false,
  dnd: false,
  dispute_open: false,
  ptp_active: false,
  already_paid: false,
  contacts_last_7d: 0,
  touches_this_case: 0,
  hours_since_failure: 40,
  reconciled: true,
  contact_captured: true,
  last4: "4242",
  contact: "+919800000001",
}

const PRESETS = {
  iff: { label: "IFF salary retry", extra: { error_reason: "insufficient_funds", hours_since_failure: 40 } },
  voice: {
    label: "₹50,001 voice",
    extra: {
      amount_paise: 5_000_100,
      prefer_voice: true,
      voice_consent: true,
      voice_lines: ["haan 42", "kal"],
      hours_since_failure: 40,
    },
  },
  cart: {
    label: "Abandoned cart",
    extra: {
      loss_class: "checkout_abandonment",
      error_reason: "payment_cancelled",
      contact_captured: true,
    },
  },
  dnd: { label: "DND trap", extra: { dnd: true, suppressed: true } },
  classb: { label: "Class B", extra: { error_reason: "order_amount_mismatch", error_source: "business" } },
} as const

type Preset = keyof typeof PRESETS

export default function RunPage() {
  const [preset, setPreset] = useState<Preset>("iff")
  const [body, setBody] = useState(() => JSON.stringify({ ...BASE, id: "case-run", ...PRESETS.iff.extra }, null, 2))
  const [out, setOut] = useState<(CaseRow & { approval_id?: string }) | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const apply = (id: Preset) => {
    setPreset(id)
    setBody(JSON.stringify({ ...BASE, id: `case-run-${id}`, ...PRESETS[id].extra }, null, 2))
  }

  const run = async () => {
    let cse: Record<string, unknown>
    try {
      cse = JSON.parse(body)
    } catch {
      setErr("Body is not valid JSON")
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const row = await api.runCase({ case: cse })
      setOut(row)
    } catch (e) {
      setOut(null)
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Run case"
        lede="POST /cases/run against the live engine. High-value voice is how you create an approval. The Awaaz page is the FSM only."
      />
      {err ? <Banner kind="danger">{err}</Banner> : null}
      <Panel
        title="Case JSON"
        actions={
          <SegmentedControl
            ariaLabel="Trap preset"
            value={preset}
            onChange={apply}
            options={Object.entries(PRESETS).map(([id, p]) => ({ id: id as Preset, label: p.label }))}
          />
        }
      >
        <textarea className="textarea" aria-label="Case JSON" value={body} onChange={(e) => setBody(e.target.value)} rows={18} style={{ minHeight: 280 }} />
        <div className="btn-row" style={{ marginTop: 12 }}>
          <Button variant="primary" disabled={busy} onClick={() => void run()}>
            {busy ? "Running..." : "Run"}
          </Button>
          <Link className="btn" href="/approvals">
            Approvals
          </Link>
        </div>
      </Panel>
      {out ? (
        <Panel title="Verdict">
          <p>
            <Badge>{out.verdict?.effect || "n/a"}</Badge> {out.verdict?.reason_code || ""} · {inr(out.amount_paise)} ·{" "}
            <Link href={`/cases/${out.case_id}`}>{out.case_id}</Link>
            {out.approval_id ? ` · approval ${out.approval_id}` : ""}
          </p>
          <JsonView value={out} label="result" />
        </Panel>
      ) : null}
    </>
  )
}
