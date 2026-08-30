"use client"

import { useMemo, useState } from "react"
import { EvalGate } from "@/components/EvalGate"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { ConfirmButton } from "@/components/ui/ConfirmButton"
import { CopyButton } from "@/components/ui/CopyButton"
import { JsonView } from "@/components/ui/JsonView"
import { Pager, Table, Td, Tr } from "@/components/ui/DataTable"
import { PageHeader } from "@/components/ui/PageHeader"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { useToast } from "@/components/ui/Toast"
import { api } from "@/lib/api"
import { downloadCsv, toCsv } from "@/lib/csv"
import { dt, hashShort } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

const PAGE = 25

export default function AuditPage() {
  const { data: audit, err, loading, reload } = useFetch((signal) => api.audit(signal), { pollMs: 8000 })
  const [page, setPage] = useState(1)
  const [q, setQ] = useState("")
  const [open, setOpen] = useState<Record<string, unknown> | null>(null)
  const [forcedBreak, setForcedBreak] = useState<string | null>(null)
  const toast = useToast()
  const rows = useMemo(() => {
    const all = audit?.rows || []
    if (!q) return all
    return all.filter((r) => `${r.seq} ${r.action} ${r.case_id} ${r.actor}`.toLowerCase().includes(q.toLowerCase()))
  }, [audit, q])

  if (err) return <EvalGate error={err} onReady={reload} />

  const pages = Math.max(1, Math.ceil(rows.length / PAGE))
  const slice = rows.slice((page - 1) * PAGE, page * PAGE)
  const last = rows.length ? String(rows[rows.length - 1]?.occurred_at || "") : ""

  return (
    <>
      <PageHeader
        title="Audit chain"
        lede="Hash-linked rows. Tamper flips one action in memory and re-hashes. It does not write the break."
        actions={
          <div className="btn-row">
            <Button
              disabled={rows.length === 0}
              onClick={() =>
                downloadCsv(
                  "audit.csv",
                  toCsv(rows, ["seq", "action", "actor", "case_id", "policy_version", "policy_hash", "occurred_at", "entry_hash"]),
                )
              }
            >
              Export CSV
            </Button>
            <ConfirmButton
              confirmLabel="Verify now"
              onConfirm={async () => {
                try {
                  const r = await api.verify()
                  setForcedBreak(r.ok ? null : r.msg)
                  toast(r.ok ? "ok" : "bad", r.msg)
                  reload()
                } catch (e) {
                  toast("bad", e instanceof Error ? e.message : String(e))
                }
              }}
            >
              Re-verify
            </ConfirmButton>
            <ConfirmButton
              danger
              confirmLabel="This flips action on row 4 in memory"
              onConfirm={async () => {
                try {
                  const r = await api.tamper()
                  if (!r.ok) setForcedBreak(r.msg)
                  toast(r.ok ? "ok" : "bad", `seq ${r.tampered_seq} ${r.msg}`)
                } catch (e) {
                  toast("bad", e instanceof Error ? e.message : String(e))
                }
              }}
            >
              Tamper one row
            </ConfirmButton>
          </div>
        }
      />
      {loading || !audit ? (
        <TableSkeleton />
      ) : (
        <>
          <Banner kind={forcedBreak || !audit.ok ? "danger" : "ok"}>
            {forcedBreak || !audit.ok ? "broken" : "verified"} · {forcedBreak || audit.msg} · source {audit.source || "eval"} · {rows.length} rows
            {last ? ` · last ${dt(last)}` : ""}
          </Banner>
          <div className="filters">
            <input className="input" placeholder="Filter action, case, actor" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} aria-label="Filter audit" />
          </div>
          <Table>
            <thead>
              <tr>
                <th>seq</th>
                <th>action</th>
                <th>actor</th>
                <th>case</th>
                <th>policy</th>
                <th>when</th>
                <th>hash</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const hash = String(r.entry_hash || "")
                return (
                  <Tr key={String(r.seq)} onSelect={() => setOpen(r)}>
                    <Td className="tabular">{String(r.seq)}</Td>
                    <Td>{String(r.action)}</Td>
                    <Td className="muted">{String(r.actor || "")}</Td>
                    <Td className="mono">{String(r.case_id || "")}</Td>
                    <Td className="mono faint" title={String(r.policy_hash || "")}>
                      {String(r.policy_version || "")} {hashShort(String(r.policy_hash || ""))}
                    </Td>
                    <Td className="muted">{dt(String(r.occurred_at || ""))}</Td>
                    <Td>
                      <span className="mono" title={hash}>
                        {hashShort(hash)}
                      </span>{" "}
                      {hash ? <CopyButton text={hash} /> : null}
                    </Td>
                  </Tr>
                )
              })}
            </tbody>
          </Table>
          <Pager page={page} pages={pages} total={rows.length} onPage={setPage} />
        </>
      )}
      {open ? (
        <div className="drawer" role="dialog" aria-label="Audit payload">
          <div className="btn-row" style={{ marginBottom: 12 }}>
            <strong>seq {String(open.seq)}</strong>
            <Button variant="ghost" onClick={() => setOpen(null)}>
              Close
            </Button>
          </div>
          <JsonView value={open} label="row" />
        </div>
      ) : null}
    </>
  )
}
