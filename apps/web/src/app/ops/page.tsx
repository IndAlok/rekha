"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { ConfirmButton } from "@/components/ui/ConfirmButton"
import { Field } from "@/components/ui/Field"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Table, Td } from "@/components/ui/DataTable"
import { useToast } from "@/components/ui/Toast"
import { ApiError, api, inr } from "@/lib/api"
import { dt } from "@/lib/format"
import { getMaskPii, getOpsToken, redact, setMaskPii, setOpsToken } from "@/lib/prefs"
import { useFetch } from "@/lib/useLoad"

export default function OpsPage() {
  const { data: status, err, reload } = useFetch((signal) => api.status(signal), { pollMs: 8000 })
  const { data: ledger } = useFetch((signal) => api.ledger(undefined, signal))
  const [busy, setBusy] = useState(false)
  const [token, setToken] = useState("")
  const [saved, setSaved] = useState(false)
  const [mask, setMask] = useState(false)
  const [custId, setCustId] = useState("")
  const [custOut, setCustOut] = useState<string | null>(null)
  const toast = useToast()
  const kill = Boolean(status?.kill_switch)

  useEffect(() => {
    setToken(getOpsToken())
    setMask(getMaskPii())
  }, [])

  return (
    <>
      <PageHeader title="Status" lede="Scheduler drains deferred jobs and re-evaluates policy at dispatch. Kill-switch state persists." />
      {err ? <Banner kind="danger">{err instanceof Error ? err.message : String(err)}. Start the API with make api or make serve.</Banner> : null}
      {kill ? <Banner kind="danger">Kill switch is engaged. Outreach and silent retries are blocked.</Banner> : null}
      <div className="grid-3">
        <Panel title="API">
          <div className={`n ${status?.ok ? "ok" : "bad"}`} style={{ fontSize: 24, fontWeight: 650 }}>
            {status?.ok ? "up" : "down"}
          </div>
          <p className="lede">env {status?.env || "n/a"}</p>
        </Panel>
        <Panel title="Eval">
          <div className="n" style={{ fontSize: 24, fontWeight: 650 }}>
            {status?.eval_ready ? "ready" : "empty"}
          </div>
        </Panel>
        <Panel title="Scheduler">
          <div className="n" style={{ fontSize: 24, fontWeight: 650 }}>
            {status?.scheduler?.up ? "running" : "off"}
          </div>
        </Panel>
        <Panel title="Live audit rows">
          <div className="n tabular" style={{ fontSize: 24, fontWeight: 650 }}>
            {status?.live_audit_rows ?? 0}
          </div>
        </Panel>
        <Panel title="Database">
          <div className="n" style={{ fontSize: 20, fontWeight: 600 }}>
            {status?.database || "sqlite"}
          </div>
          <p className="lede">Postgres in production. SQLite when you run make serve.</p>
        </Panel>
        <Panel title="Kill switch">
          <div className={`n ${kill ? "bad" : "ok"}`} style={{ fontSize: 24, fontWeight: 650 }}>
            {kill ? "ENGAGED" : "clear"}
          </div>
          <div style={{ marginTop: 12 }}>
            <ConfirmButton
              danger={!kill}
              variant={kill ? "primary" : "danger"}
              confirmLabel={kill ? "Release it" : "Engage it"}
              onConfirm={async () => {
                try {
                  await api.kill(!kill)
                  reload()
                  toast("ok", kill ? "Kill switch released" : "Kill switch engaged")
                } catch (e) {
                  toast("bad", e instanceof Error ? e.message : String(e))
                }
              }}
            >
              {kill ? "Release" : "Engage"}
            </ConfirmButton>
          </div>
        </Panel>
      </div>
      <Panel title="Ops token" lede="Stored in this browser only. Sent as X-Ops-Token on every mutating call. Required outside REKHA_ENV=dev.">
        <Field label="Token">
          <input
            className="input mono"
            type="password"
            value={token}
            onChange={(e) => {
              setToken(e.target.value)
              setSaved(false)
            }}
            autoComplete="off"
          />
        </Field>
        <div className="btn-row" style={{ marginTop: 12 }}>
          <Button
            variant="primary"
            onClick={() => {
              setOpsToken(token.trim())
              setSaved(true)
              toast("ok", token.trim() ? "Token saved" : "Token cleared")
            }}
          >
            Save token
          </Button>
          {saved ? <span className="ok">saved</span> : null}
        </div>
        <p className="lede" style={{ marginTop: 10 }}>
          Auth required: {status?.ops_auth_required ? "yes" : "no (dev with empty OPS_TOKEN)"}. Webhook secret:{" "}
          {status?.webhook_secret_set ? "set" : "absent"}. Payments: {status?.payments_adapter_effective || status?.payments_adapter || "sandbox"}
          {status?.payments_fallback ? " (fell back to sandbox)" : ""}. WhatsApp {status?.whatsapp_quality || "green"}.
        </p>
      </Panel>
      <Panel title="Display">
        <label className="btn-row">
          <input
            type="checkbox"
            checked={mask}
            onChange={(e) => {
              setMask(e.target.checked)
              setMaskPii(e.target.checked)
            }}
          />
          Mask PII in case views (contact, last4, name)
        </label>
      </Panel>
      <Panel title="Upcoming jobs" actions={<Link href="/jobs">All jobs</Link>}>
        {(status?.scheduler?.upcoming_jobs?.length ?? 0) === 0 ? (
          <p className="muted">None queued.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>kind</th>
                <th>case</th>
                <th>run at</th>
              </tr>
            </thead>
            <tbody>
              {status?.scheduler?.upcoming_jobs.map((j) => (
                <tr key={j.id}>
                  <Td>{j.kind}</Td>
                  <Td>
                    <Link className="mono" href={`/cases/${j.case_id}`}>
                      {j.case_id}
                    </Link>
                  </Td>
                  <Td>{dt(j.run_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
      <Panel title="Customer / complaints">
        <Field label="Customer id">
          <input className="input mono" value={custId} onChange={(e) => setCustId(e.target.value)} placeholder="cust_0001" />
        </Field>
        <div className="btn-row" style={{ marginTop: 12 }}>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const [c, p] = await Promise.all([
                  api.customer(custId.trim()).catch((e) => ({ error: e instanceof Error ? e.message : String(e) })),
                  api.complaints(custId.trim()),
                ])
                const payload = { customer: c, complaints: p }
                setCustOut(JSON.stringify(mask ? redact(payload, true) : payload, null, 2))
              } catch (e) {
                setCustOut(e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Lookup
          </Button>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const row = await api.setConsent(custId.trim(), "REVOKED")
                setCustOut(JSON.stringify(mask ? redact(row, true) : row, null, 2))
                toast("ok", "Consent revoked")
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Revoke consent
          </Button>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const row = await api.setCustomerFlags(custId.trim(), { dnd: true })
                setCustOut(JSON.stringify(mask ? redact(row, true) : row, null, 2))
                toast("ok", "DND on")
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Set DND
          </Button>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const row = await api.setCustomerFlags(custId.trim(), { legal_hold: true })
                setCustOut(JSON.stringify(mask ? redact(row, true) : row, null, 2))
                toast("ok", "Legal hold on")
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Legal hold
          </Button>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const row = await api.setCustomerFlags(custId.trim(), { opt_out: true })
                setCustOut(JSON.stringify(mask ? redact(row, true) : row, null, 2))
                toast("ok", "Opt-out on")
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
          >
            Opt out
          </Button>
          <Button
            onClick={async () => {
              if (!custId.trim()) return
              try {
                const row = await api.fileComplaint(custId.trim())
                setCustOut(JSON.stringify(row, null, 2))
                toast("ok", row.throttled ? "Complaint recorded. Circuit open." : "Complaint recorded")
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
          >
            File complaint
          </Button>
        </div>
        {custOut ? <pre className="json" style={{ marginTop: 12 }}>{custOut}</pre> : null}
      </Panel>
      <Panel title="WhatsApp quality">
        <p className="lede">Red DEFERS WhatsApp. Default is green.</p>
        <div style={{ marginTop: 12 }}>
          <SegmentedControl
            ariaLabel="WhatsApp quality"
            value={(status?.whatsapp_quality as "green" | "yellow" | "red") || "green"}
            onChange={async (v) => {
              try {
                await api.setWhatsappQuality(v)
                reload()
                toast("ok", `WhatsApp ${v}`)
              } catch (e) {
                toast("bad", e instanceof Error ? e.message : String(e))
              }
            }}
            options={[
              { id: "green", label: "Green" },
              { id: "yellow", label: "Yellow" },
              { id: "red", label: "Red" },
            ]}
          />
        </div>
      </Panel>
      <Panel title="Degraded slices">
        {(status?.degradation?.length ?? 0) === 0 ? (
          <p className="muted">No degraded slices.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th>slice</th>
                <th className="num">attempts</th>
                <th className="num">rupees at risk</th>
              </tr>
            </thead>
            <tbody>
              {(status?.degradation || []).map((row, i) => (
                <tr key={String(row.key || i)}>
                  <Td className="mono">{String(row.slice || row.key || "n/a")}</Td>
                  <Td className="num">{String(row.attempts ?? "")}</Td>
                  <Td className="num">{inr(Number(row.rupees_at_risk_paise || row.rupees_at_risk || 0))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Panel>
      <Panel title="Ledger" actions={<Link href="/ledger">Open ledger</Link>}>
        <p>
          Agent {inr(ledger?.totals.agent_paise ?? 0)} · self-cure {inr(ledger?.totals.self_cure_paise ?? 0)} ·{" "}
          {ledger?.totals.entries ?? 0} entries
        </p>
      </Panel>
      <Button
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          try {
            await api.runEval(42)
            reload()
            toast("ok", "Eval finished. Golden was not rewritten.")
          } catch (e) {
            toast("bad", e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
          } finally {
            setBusy(false)
          }
        }}
      >
        {busy ? "Running eval..." : "Run eval again"}
      </Button>
    </>
  )
}
