"use client"

import Link from "next/link"
import { Suspense } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { Badge } from "@/components/ui/Badge"
import { Banner } from "@/components/ui/Banner"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { PageHeader } from "@/components/ui/PageHeader"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Table, Td } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api } from "@/lib/api"
import { downloadCsv, toCsv } from "@/lib/csv"
import { dt, inr } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

type Attr = "all" | "agent" | "self_cure"

function LedgerInner() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const attribution = (params.get("attribution") || "all") as Attr
  const { data, err, loading } = useFetch((signal) => api.ledger(attribution, signal), {
    deps: [attribution],
    pollMs: 8000,
  })
  const totals = data?.totals
  const rows = data?.rows || []

  const setAttr = (v: Attr) => {
    const next = new URLSearchParams(params.toString())
    if (v === "all") next.delete("attribution")
    else next.set("attribution", v)
    const qs = next.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname)
  }

  return (
    <>
      <PageHeader
        title="Ledger"
        lede="Agent only after an execute. Self-cure is a payment with no intervention. Groq does not get a ledger row."
        actions={
          <Button
            disabled={rows.length === 0}
            onClick={() =>
              downloadCsv(
                "ledger.csv",
                toCsv(rows as unknown as Array<Record<string, unknown>>, [
                  "case_id",
                  "action",
                  "channel",
                  "source_event",
                  "amount_paise",
                  "attribution",
                  "recovered_at",
                ]),
              )
            }
          >
            Export CSV
          </Button>
        }
      />
      {err ? <Banner kind="danger">{err instanceof Error ? err.message : String(err)}</Banner> : null}
      <div className="quartet">
        <div className="stat">
          <p className="cap">Attributed to agent</p>
          <div className="n">{inr(totals?.agent_paise ?? 0)}</div>
        </div>
        <div className="stat">
          <p className="cap">Self-cure</p>
          <div className="n">{inr(totals?.self_cure_paise ?? 0)}</div>
        </div>
        <div className="stat">
          <p className="cap">Entries</p>
          <div className="n">{totals?.entries ?? 0}</div>
        </div>
        <div className="stat">
          <p className="cap">Live webhooks</p>
          <div className="n" style={{ fontSize: 16, fontWeight: 600 }}>
            <Link href="/webhooks">Open console</Link>
          </div>
        </div>
      </div>
      <div className="filters">
        <SegmentedControl
          ariaLabel="Attribution"
          value={attribution}
          onChange={setAttr}
          options={[
            { id: "all", label: "All" },
            { id: "agent", label: "Agent" },
            { id: "self_cure", label: "Self-cure" },
          ]}
        />
      </div>
      {loading && rows.length === 0 ? <TableSkeleton /> : null}
      {!loading && rows.length === 0 ? <EmptyState title="No ledger entries yet">Send payment.authorized after a failed payment.</EmptyState> : null}
      {rows.length > 0 ? (
        <Table>
          <thead>
            <tr>
              <th>case</th>
              <th>action</th>
              <th>channel</th>
              <th>source</th>
              <th className="num">amount</th>
              <th>attribution</th>
              <th>when</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.case_id}-${i}`}>
                <Td>
                  <Link className="mono" href={`/cases/${r.case_id}`}>
                    {r.case_id}
                  </Link>
                </Td>
                <Td>{r.action || ""}</Td>
                <Td>{r.channel || ""}</Td>
                <Td>{r.source_event}</Td>
                <Td className="num">{inr(r.amount_paise)}</Td>
                <Td>
                  <Badge>{r.attribution}</Badge>
                </Td>
                <Td className="muted">{dt(r.recovered_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </>
  )
}

export default function LedgerPage() {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <LedgerInner />
    </Suspense>
  )
}
