"use client"

import Link from "next/link"
import { Suspense, useMemo } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { EvalGate } from "@/components/EvalGate"
import { Badge } from "@/components/ui/Badge"
import { EmptyState } from "@/components/ui/EmptyState"
import { PageHeader } from "@/components/ui/PageHeader"
import { Table, Td } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api } from "@/lib/api"
import { useFetch } from "@/lib/useLoad"

function ComplianceInner() {
  const { data, err, loading, reload } = useFetch((signal) => api.blocked(signal))
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const rule = params.get("rule") || "all"
  const rows = useMemo(() => data || [], [data])
  const rules = useMemo(() => Array.from(new Set(rows.map((r) => String(r.rule || "")))), [rows])
  const shown = rows.filter((r) => rule === "all" || String(r.rule) === rule)

  if (err) return <EvalGate error={err} onReady={reload} />

  return (
    <>
      <PageHeader title="Blocked actions" lede={`${shown.length} DENY rows. Each keeps the rule id and the matched-rule set.`} />
      <div className="filters">
        <select
          className="select"
          value={rule}
          onChange={(e) => {
            const next = new URLSearchParams(params.toString())
            if (e.target.value === "all") next.delete("rule")
            else next.set("rule", e.target.value)
            const qs = next.toString()
            router.replace(qs ? `${pathname}?${qs}` : pathname)
          }}
          aria-label="Rule"
        >
          <option value="all">All rules</option>
          {rules.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>
      {loading ? <TableSkeleton /> : null}
      {!loading && shown.length === 0 ? (
        <EmptyState title="No blocked actions">Eval DENY rows land here. Try another rule filter.</EmptyState>
      ) : null}
      {!loading && shown.length > 0 ? (
        <Table>
          <thead>
            <tr>
              <th>case</th>
              <th>action</th>
              <th>rule</th>
              <th>trap</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={`${r.case_id}-${i}`}>
                <Td>
                  <Link href={`/cases/${String(r.case_id)}`}>{String(r.case_id)}</Link>
                </Td>
                <Td>{String(r.action)}</Td>
                <Td>
                  <Badge tone="warning">{String(r.rule)}</Badge>
                </Td>
                <Td>{String(r.trap || "")}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </>
  )
}

export default function CompliancePage() {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <ComplianceInner />
    </Suspense>
  )
}
