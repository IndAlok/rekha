"use client"

import Link from "next/link"
import { useState } from "react"
import { Banner } from "@/components/ui/Banner"
import { ConfirmButton } from "@/components/ui/ConfirmButton"
import { EmptyState } from "@/components/ui/EmptyState"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Table, Td, Tr } from "@/components/ui/DataTable"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { useToast } from "@/components/ui/Toast"
import { api, type Job } from "@/lib/api"
import { dt } from "@/lib/format"
import { useFetch } from "@/lib/useLoad"

type Filter = "all" | "pending" | "running" | "done" | "failed"

export default function JobsPage() {
  const [filter, setFilter] = useState<Filter>("all")
  const { data, err, loading, reload } = useFetch((signal) => api.jobs(filter, signal), { deps: [filter], pollMs: 8000 })
  const [busy, setBusy] = useState<number | null>(null)
  const toast = useToast()
  const jobs = data?.jobs || []

  const cancel = async (job: Job) => {
    setBusy(job.id)
    try {
      await api.cancelJob(job.id)
      toast("ok", `Job ${job.id} cancelled`)
      reload()
    } catch (e) {
      toast("bad", e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader title="Jobs" lede="Deferred outreach and send_after. The scheduler claims a lease, retries three times, then marks failed." />
      {err ? <Banner kind="danger">{err instanceof Error ? err.message : String(err)}</Banner> : null}
      <div className="filters">
        <SegmentedControl
          ariaLabel="Job status"
          value={filter}
          onChange={setFilter}
          options={[
            { id: "all", label: "All" },
            { id: "pending", label: "Pending" },
            { id: "running", label: "Running" },
            { id: "done", label: "Done" },
            { id: "failed", label: "Failed" },
          ]}
        />
      </div>
      {loading && jobs.length === 0 ? <TableSkeleton /> : null}
      {!loading && jobs.length === 0 ? (
        <Panel>
          <EmptyState title="No jobs">Quiet-hour DEFER and future send_after land here.</EmptyState>
        </Panel>
      ) : null}
      {jobs.length > 0 ? (
        <Table>
          <thead>
            <tr>
              <th>id</th>
              <th>kind</th>
              <th>case</th>
              <th>status</th>
              <th>attempts</th>
              <th>run at</th>
              <th>lease</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <Tr key={j.id}>
                <Td className="tabular">{j.id}</Td>
                <Td>{j.kind}</Td>
                <Td>
                  <Link className="mono" href={`/cases/${j.case_id}`}>
                    {j.case_id}
                  </Link>
                </Td>
                <Td>{j.status}</Td>
                <Td className="tabular">{j.attempts}</Td>
                <Td className="muted">{dt(j.run_at)}</Td>
                <Td className="muted">{j.lease_expires_at ? dt(j.lease_expires_at) : "n/a"}</Td>
                <Td>
                  {j.status === "pending" || j.status === "running" ? (
                    <ConfirmButton
                      danger
                      busy={busy === j.id}
                      confirmLabel="Cancel this job"
                      onConfirm={() => cancel(j)}
                    >
                      Cancel
                    </ConfirmButton>
                  ) : null}
                </Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      ) : null}
    </>
  )
}
