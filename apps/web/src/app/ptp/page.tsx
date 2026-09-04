"use client"

import Link from "next/link"
import { EvalGate } from "@/components/EvalGate"
import { Badge } from "@/components/ui/Badge"
import { EmptyState } from "@/components/ui/EmptyState"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { Table, Td } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api } from "@/lib/api"
import { inr } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

export default function PtpPage() {
  const { data, err, loading, reload } = useFetch((signal) => api.ptp(signal), { pollMs: 8000 })
  const rows = data || []

  if (err) return <EvalGate error={err} onReady={reload} />

  return (
    <>
      <PageHeader title="Promises" lede="An open promise freezes dunning. A renegotiation writes a new row. The parent is not edited." />
      <Panel>
        {loading && rows.length === 0 ? <TableSkeleton /> : null}
        {!loading && rows.length === 0 ? <EmptyState title="No promise cases">Capture a PTP from Awaaz or Run case.</EmptyState> : null}
        {rows.length > 0 ? (
          <Table>
            <thead>
              <tr>
                <th>id</th>
                <th>customer</th>
                <th className="num">amount</th>
                <th>due</th>
                <th>state</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const broken = Boolean(r.ptp_breached) || r.state === "Broken"
                const id = String(r.case_id || r.id || "")
                return (
                  <tr key={id}>
                    <Td className="mono">
                      {id ? <Link href={`/cases/${id}`}>{id}</Link> : "n/a"}
                    </Td>
                    <Td>{String(r.customer_id || "")}</Td>
                    <Td className="num">{inr(Number(r.amount_paise || r.promised_amount_paise || 0))}</Td>
                    <Td className="muted">{String(r.promised_date || "n/a")}</Td>
                    <Td>
                      <Badge tone={broken ? "negative" : "info"}>{String(r.state || (broken ? "Broken" : "Open"))}</Badge>
                    </Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        ) : null}
      </Panel>
    </>
  )
}
