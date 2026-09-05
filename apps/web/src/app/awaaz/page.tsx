"use client"

import Link from "next/link"
import { useState } from "react"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { Field } from "@/components/ui/Field"
import { KeyVal } from "@/components/ui/KeyVal"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Transcript } from "@/components/ui/Transcript"
import { api, inr, type AwaazSession } from "@/lib/api"

const BASE = {
  id: "c-awaaz-demo",
  merchant_name: "NoonCart",
  first_name: "Riya",
  last4: "4242",
}

const PRESETS = {
  ptp: { label: "Verify + PTP", amount: 49900, lines: "haan main Riya hoon, 42\nkal de dungi\nok" },
  wrong: { label: "Wrong digits", amount: 49900, lines: "haan 99\n99 again" },
  distress: { label: "Distress stop", amount: 49900, lines: "don't call me\nstop calling" },
} as const

type Preset = keyof typeof PRESETS

export default function AwaazPage() {
  const [preset, setPreset] = useState<Preset>("ptp")
  const [lines, setLines] = useState<string>(PRESETS.ptp.lines)
  const [amount, setAmount] = useState<number>(PRESETS.ptp.amount)
  const [session, setSession] = useState<AwaazSession | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const apply = (id: Preset) => {
    setPreset(id)
    setLines(PRESETS[id].lines)
    setAmount(PRESETS[id].amount)
  }

  const run = () => {
    setBusy(true)
    setErr(null)
    api
      .awaaz({ ...BASE, amount_paise: amount }, lines.split("\n").map((l) => l.trim()).filter(Boolean))
      .then(setSession)
      .catch((e) => {
        setSession(null)
        setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => setBusy(false))
  }

  return (
    <>
      <PageHeader
        title="Awaaz"
        lede="Scripted transcript fixture driven by the real FSM. No audio pipeline is claimed. This page cannot create an approval. Groq is not on this path. For ₹50,001 voice, use Approvals or Run case."
        actions={
          <Link className="btn" href="/approvals">
            Open approvals
          </Link>
        }
      />
      <Banner>The caller states the last two digits. The agent never reads them out.</Banner>
      <Panel
        title="Session"
        actions={
          <SegmentedControl
            ariaLabel="Preset"
            value={preset}
            onChange={apply}
            options={Object.entries(PRESETS).map(([id, p]) => ({ id: id as Preset, label: p.label }))}
          />
        }
      >
        <Field label={`Amount, paise (${inr(amount)})`}>
          <input className="input" type="number" aria-label="Amount in paise" value={amount} onChange={(e) => setAmount(Number(e.target.value) || 0)} />
        </Field>
        <Field label="Caller lines, one per turn">
          <textarea className="textarea" aria-label="Caller lines" value={lines} onChange={(e) => setLines(e.target.value)} rows={4} style={{ fontFamily: "inherit", minHeight: 90 }} />
        </Field>
        <div style={{ marginTop: 12 }}>
          <Button variant="primary" disabled={busy} onClick={run}>
            {busy ? "Running..." : "Run session"}
          </Button>
        </div>
      </Panel>
      {err ? <Banner kind="danger">{err}</Banner> : null}
      {session ? (
        <Panel title="Disposition">
          <Banner kind={session.stopped ? "danger" : "ok"}>
            verified={String(session.verified)} stopped={String(session.stopped)} reason={session.stop_reason || "none"}
            {session.compliance_flags.length > 0 ? ` flags=${session.compliance_flags.join(",")}` : ""}
          </Banner>
          <Transcript turns={session.turns} />
          {session.captured_ptp ? (
            <KeyVal
              rows={[
                ["Promise", inr(session.captured_ptp.amount_paise)],
                ["By", session.captured_ptp.date],
              ]}
            />
          ) : null}
        </Panel>
      ) : null}
    </>
  )
}
