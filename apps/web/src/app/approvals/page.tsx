"use client"

import Link from "next/link"
import { useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { ConfirmButton } from "@/components/ui/ConfirmButton"
import { EmptyState } from "@/components/ui/EmptyState"
import { KeyVal } from "@/components/ui/KeyVal"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Table, Td, Tr } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { useToast } from "@/components/ui/Toast"
import { ApiError, api, type Approval } from "@/lib/api"
import { dt, inr } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

const VOICE_CASE = {
  customer_id: "cust-dash-appr",
  merchant_name: "NoonCart",
  first_name: "Riya",
  last4: "4242",
  prefer_voice: true,
  voice_consent: true,
  voice_lines: ["haan 42", "kal"],
  amount_paise: 5_000_100,
  loss_class: "payment_failure",
  error_reason: "insufficient_funds",
  error_source: "customer",
  consent_status: "GRANTED",
  contacts_last_7d: 0,
  touches_this_case: 0,
  hours_since_failure: 40,
  contact: "+919800000003",
}

type Tab = "pending" | "approved" | "rejected" | "timed_out" | "all"

export default function ApprovalsPage() {
  const [tab, setTab] = useState<Tab>("pending")
  const { data, err, loading, reload } = useFetch((signal) => api.approvals(tab, signal), { deps: [tab], pollMs: 8000 })
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [killBanner, setKillBanner] = useState(false)
  const toast = useToast()
  const rows = data || []
  const current = rows.find((r) => r.id === selected) || rows[0] || null

  const decide = (id: string, decision: "approve" | "reject") => {
    setBusy(id)
    setKillBanner(false)
    api
      .decideApproval(id, decision)
      .then((r) => {
        toast("ok", `${id} ${r.status}`)
        reload()
      })
      .catch((e) => {
        if (e instanceof ApiError && e.code === "KILL_SWITCH") {
          setKillBanner(true)
          toast("bad", "Kill switch is engaged")
        } else if (e instanceof ApiError && e.code === "POLICY_CHANGED") {
          toast("bad", "Policy changed since this request. Rejected.")
          reload()
        } else if (e instanceof ApiError && e.code === "APPROVAL_CLOSED") {
          toast("bad", "This approval is already closed")
          reload()
        } else {
          toast("bad", e instanceof Error ? e.message : String(e))
        }
      })
      .finally(() => setBusy(null))
  }

  const create = () => {
    setCreating(true)
    api
      .runCase({ case: { ...VOICE_CASE, id: `case-dash-${Date.now()}` } })
      .then((r) => {
        toast("ok", r.verdict?.effect === "REQUIRE_APPROVAL" ? "Approval created" : `Effect ${r.verdict?.effect}`)
        setTab("pending")
        reload()
      })
      .catch((e) => toast("bad", e instanceof Error ? e.message : String(e)))
      .finally(() => setCreating(false))
  }

  return (
    <>
      <PageHeader
        title="Approvals"
        lede="A human decides. The executor runs, or the case closes. Pending rows auto-deny after 2 days. Awaaz cannot create these."
        actions={
          <div className="btn-row">
            <Link className="btn" href="/run">
              Run case
            </Link>
            <Button variant="primary" disabled={creating} onClick={create}>
              {creating ? "Creating..." : "Run a ₹50,001 voice case"}
            </Button>
          </div>
        }
      />
      {killBanner ? (
        <Banner kind="danger">
          Approve was blocked. Kill switch is on. Check <Link href="/ops">Status</Link>.
        </Banner>
      ) : null}
      {err ? <Banner kind="danger">{err instanceof Error ? err.message : String(err)}</Banner> : null}
      <div className="filters">
        <SegmentedControl
          ariaLabel="Approval status"
          value={tab}
          onChange={setTab}
          options={[
            { id: "pending", label: "Pending" },
            { id: "approved", label: "Approved" },
            { id: "rejected", label: "Rejected" },
            { id: "timed_out", label: "Timed out" },
            { id: "all", label: "All" },
          ]}
        />
      </div>
      {loading && rows.length === 0 ? <TableSkeleton /> : null}
      {!loading && rows.length === 0 ? (
        <Panel>
          <EmptyState
            title={tab === "pending" ? "No approvals pending" : "No rows in this tab"}
            action={tab === "pending" ? <Button onClick={create}>Run a ₹50,001 voice case</Button> : undefined}
          >
            High-value money actions need a person. POST /cases/run with amount_paise 5000100 and prefer_voice true. The Awaaz page is the FSM only.
          </EmptyState>
        </Panel>
      ) : null}
      {rows.length > 0 ? (
        <div className="split">
          <Panel title={`${rows.length} ${tab}`}>
            <Table>
              <thead>
                <tr>
                  <th>case</th>
                  <th className="num">amount</th>
                  <th>status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <Tr key={a.id} selected={current?.id === a.id} onSelect={() => setSelected(a.id)}>
                    <Td>
                      <span className="mono">{a.case_id}</span>
                    </Td>
                    <Td className="num">{inr(a.amount_paise)}</Td>
                    <Td>{a.status || tab}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </Panel>
          {current ? (
            <Detail row={current} busy={busy === current.id} onDecide={decide} canDecide={(current.status || tab) === "pending"} />
          ) : null}
        </div>
      ) : null}
    </>
  )
}

function Detail({
  row,
  busy,
  onDecide,
  canDecide,
}: {
  row: Approval
  busy: boolean
  onDecide: (id: string, d: "approve" | "reject") => void
  canDecide: boolean
}) {
  return (
    <Panel title={row.case_id} lede={`Expires ${dt(row.expires_at)}`}>
      <KeyVal
        rows={[
          ["Amount", inr(row.amount_paise)],
          ["Action", `${row.proposal?.action || "n/a"} / ${row.proposal?.channel || "n/a"}`],
          ["Role", row.approver_role],
          ["Status", row.status || "pending"],
          ["Reason", row.proposal?.reason],
        ]}
      />
      <p style={{ marginTop: 12 }}>
        <Badge>REQUIRE_APPROVAL</Badge>
      </p>
      {canDecide ? (
        <div className="btn-row" style={{ marginTop: 16 }}>
          <ConfirmButton confirmLabel="Approve and execute" busy={busy} variant="primary" onConfirm={() => onDecide(row.id, "approve")}>
            Approve
          </ConfirmButton>
          <ConfirmButton confirmLabel="Reject this case" busy={busy} danger onConfirm={() => onDecide(row.id, "reject")}>
            Reject
          </ConfirmButton>
        </div>
      ) : (
        <p className="lede" style={{ marginTop: 12 }}>
          Already decided{row.decided_at ? ` at ${dt(row.decided_at)}` : ""}.
        </p>
      )}
    </Panel>
  )
}
