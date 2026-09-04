"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { useEffect, useState } from "react"
import { EvalGate } from "@/components/EvalGate"
import { Badge } from "@/components/ui/Badge"
import { JsonView } from "@/components/ui/JsonView"
import { KeyVal } from "@/components/ui/KeyVal"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { Skeleton } from "@/components/ui/Skeleton"
import { Table, Td } from "@/components/ui/DataTable"
import { Timeline } from "@/components/ui/Timeline"
import { api, type CaseRow } from "@/lib/api"
import { dt, inr } from "@/lib/format"
import { getMaskPii, redact } from "@/lib/prefs"
import { useFetch } from "@/lib/useLoad"

type Tab = "trail" | "verdict" | "raw"

export default function CaseDetailPage() {
  const params = useParams<{ id: string }>()
  const { data: row, err, loading, reload } = useFetch((signal) => api.case(params.id, signal), { deps: [params.id] })
  const { data: nav } = useFetch((signal) => api.neighbors(params.id, signal), { deps: [params.id] })
  const [tab, setTab] = useState<Tab>("trail")
  const [mask, setMask] = useState(false)

  useEffect(() => {
    setMask(getMaskPii())
    const on = () => setMask(getMaskPii())
    window.addEventListener("rekha:prefs", on)
    return () => window.removeEventListener("rekha:prefs", on)
  }, [])

  if (err) return <EvalGate error={err} onReady={reload} />
  if (loading || !row) {
    return (
      <>
        <PageHeader title={params.id} />
        <Skeleton />
      </>
    )
  }

  const shown = (mask ? (redact(row, true) as CaseRow) : row)

  return (
    <>
      <PageHeader
        title={row.case_id}
        lede={
          <>
            {inr(row.amount_paise)} · <Badge>{row.verdict?.effect || row.status || "live"}</Badge>
            {row.trap ? (
              <>
                {" "}
                <Badge>{row.trap}</Badge>
              </>
            ) : null}
            {row.source === "live" ? (
              <>
                {" "}
                <Badge tone="info">live</Badge>
              </>
            ) : null}
            {row.experiment_arm ? (
              <>
                {" "}
                <Badge>arm {row.experiment_arm}</Badge>
              </>
            ) : null}
          </>
        }
        actions={
          <div className="btn-row">
            <Link className="btn" href="/cases">
              Back to cases
            </Link>
            {nav?.prev ? (
              <Link className="btn" href={`/cases/${nav.prev}`}>
                Previous
              </Link>
            ) : null}
            {nav?.next ? (
              <Link className="btn" href={`/cases/${nav.next}`}>
                Next
              </Link>
            ) : null}
          </div>
        }
      />
      <div className="grid-2">
        <Panel title="Rekha">
          <KeyVal
            rows={[
              ["Class", shown.diagnosis?.recoverability_class],
              ["Engine", shown.proposal?.engine],
              ["Action", shown.proposal?.action],
              ["Channel", shown.proposal?.channel],
              ["Reason", shown.verdict?.reason_code],
              ["Recovered", shown.recovered ? `yes (${shown.recovery_source})` : "no"],
              ["Scheduled", shown.scheduled ? "yes" : "no"],
            ]}
          />
        </Panel>
        <Panel title="Holdout">
          {row.holdout_recovered == null ? (
            <p className="lede">Live case. Holdout comparison is on the eval batch.</p>
          ) : (
            <KeyVal
              rows={[
                ["Recovered", row.holdout_recovered ? "yes" : "no"],
                ["Same customer, status-quo engine", row.holdout_recovered === row.recovered ? "matched" : "diverged"],
              ]}
            />
          )}
        </Panel>
      </div>
      <div className="filters">
        <SegmentedControl
          ariaLabel="Case views"
          value={tab}
          onChange={setTab}
          options={[
            { id: "trail", label: "Trail" },
            { id: "verdict", label: "Verdict" },
            { id: "raw", label: "Raw" },
          ]}
        />
      </div>
      {tab === "trail" && <Trail row={shown} />}
      {tab === "verdict" && (
        <Panel title="Verdict">
          <JsonView value={shown.verdict} label="verdict" />
        </Panel>
      )}
      {tab === "raw" && (
        <Panel title="Raw">
          <JsonView value={shown} label="case" />
        </Panel>
      )}
    </>
  )
}

function Trail({ row }: { row: CaseRow }) {
  const rules = (row.verdict?.matched_rules || []) as Array<Record<string, unknown>>
  const audit = row.audit || []
  return (
    <>
      <Panel title="Trail">
        <Timeline
          steps={[
            {
              title: "Diagnose",
              body: `${row.diagnosis?.recoverability_class || "n/a"} / ${row.diagnosis?.error_reason || "n/a"}`,
            },
            {
              title: "Propose",
              body: `${row.proposal?.action || "none"} via ${row.proposal?.channel || "none"}`,
            },
            {
              title: "Policy",
              body: `${row.verdict?.effect || "n/a"}, rule ${row.verdict?.reason_code || "n/a"}`,
              extra: (
                <div style={{ marginTop: 6 }}>
                  {rules.map((r, i) => (
                    <Badge key={i}>{String(r.id || r.reason_code || "rule")}</Badge>
                  ))}
                </div>
              ),
            },
            {
              title: "Outcome",
              body: `${row.recovery_source}, ${row.recovered ? "counted" : "not counted"}`,
            },
          ]}
        />
      </Panel>
      {audit.length > 0 ? (
        <Panel title="Audit on this case">
          <Table>
            <thead>
              <tr>
                <th>action</th>
                <th>when</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a, i) => (
                <tr key={i}>
                  <Td>{String(a.action || "")}</Td>
                  <Td className="muted">{dt(String(a.occurred_at || ""))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
      {row.ledger && row.ledger.length > 0 ? (
        <Panel title="Ledger">
          <Table>
            <thead>
              <tr>
                <th>source</th>
                <th className="num">amount</th>
                <th>attribution</th>
              </tr>
            </thead>
            <tbody>
              {row.ledger.map((r, i) => (
                <tr key={i}>
                  <Td>{r.source_event}</Td>
                  <Td className="num">{inr(r.amount_paise)}</Td>
                  <Td>
                    <Badge>{r.attribution}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Panel>
      ) : null}
    </>
  )
}
