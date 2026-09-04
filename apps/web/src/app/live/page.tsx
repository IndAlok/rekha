"use client"

import Link from "next/link"
import { Badge } from "@/components/ui/Badge"
import { Banner } from "@/components/ui/Banner"
import { EmptyState } from "@/components/ui/EmptyState"
import { PageHeader } from "@/components/ui/PageHeader"
import { Table, Td } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api } from "@/lib/api"
import { ago, inr } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

export default function LivePage() {
  const { data, err, loading } = useFetch((signal) => api.liveCases(signal), { pollMs: 8000 })
  const rows = data || []

  return (
    <>
      <PageHeader title="Live cases" lede="Webhook and /cases/run traffic. Survives a restart." />
      {err ? <Banner kind="danger">{err instanceof Error ? err.message : String(err)}</Banner> : null}
      {loading && rows.length === 0 ? <TableSkeleton /> : null}
      {!loading && rows.length === 0 ? (
        <EmptyState title="No live cases yet">Send a payment.failed fixture from the webhook console.</EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <Table>
          <thead>
            <tr>
              <th>id</th>
              <th>status</th>
              <th>class</th>
              <th className="num">amount</th>
              <th>touches</th>
              <th>recovered</th>
              <th>stop</th>
              <th>updated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.case_id}>
                <Td>
                  <Link className="mono" href={`/cases/${r.case_id}`}>
                    {r.case_id}
                  </Link>
                </Td>
                <Td>
                  <Badge>{r.status}</Badge>
                </Td>
                <Td>{r.loss_class}</Td>
                <Td className="num">{inr(r.amount_paise)}</Td>
                <Td className="tabular">{r.touches}</Td>
                <Td>
                  {r.recovered ? "yes" : "no"} {r.recovery_source}
                </Td>
                <Td className="muted">{r.stop_reason || ""}</Td>
                <Td className="muted">{ago(r.updated_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </>
  )
}
