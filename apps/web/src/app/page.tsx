"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { EstimatePlot } from "@/components/charts/EstimatePlot"
import { FunnelChart } from "@/components/charts/FunnelChart"
import { GroupedBars } from "@/components/charts/GroupedBars"
import { EvalGate } from "@/components/EvalGate"
import { Badge } from "@/components/ui/Badge"
import { PageHeader } from "@/components/ui/PageHeader"
import { Panel } from "@/components/ui/Panel"
import { Skeleton } from "@/components/ui/Skeleton"
import { api, type CaseRow, type Report, type Status } from "@/lib/api"
import { inr, inrSigned, pct, pp } from "@/lib/format"

export default function OverviewPage() {
  const [report, setReport] = useState<Report | null>(null)
  const [cases, setCases] = useState<CaseRow[] | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [ledger, setLedger] = useState<{ agent_paise: number; self_cure_paise: number; entries: number } | null>(null)
  const [err, setErr] = useState<unknown>(null)

  const load = useCallback((signal?: AbortSignal) => {
    setErr(null)
    Promise.all([api.report(signal), api.cases({ signal })])
      .then(([r, c]) => {
        if (signal?.aborted) return
        setReport(r)
        setCases(c)
      })
      .catch((e) => {
        if (signal?.aborted) return
        setReport(null)
        setCases(null)
        setErr(e)
      })
    api.status(signal).then((row) => {
      if (!signal?.aborted) setStatus(row)
    }).catch(() => {
      if (!signal?.aborted) setStatus(null)
    })
    api.ledger(undefined, signal).then((row) => {
      if (!signal?.aborted) setLedger(row.totals)
    }).catch(() => {
      if (!signal?.aborted) setLedger(null)
    })
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  if (err) return <EvalGate error={err} onReady={() => load()} />
  if (!report || !cases) {
    return (
      <>
        <PageHeader title="Overview" lede="Loading the last eval." />
        <Skeleton rows={8} />
      </>
    )
  }

  const design = report.design
  const violations = Object.entries(report.violation_counts || {})
  const enginePaise: Record<string, number> = {}
  for (const row of cases) {
    if (!row.recovered) continue
    const name = row.proposal?.engine || "none"
    enginePaise[name] = (enginePaise[name] || 0) + row.amount_paise
  }
  const bars = Object.entries(enginePaise)
    .map(([label, paise]) => ({ label, paise }))
    .sort((a, b) => b.paise - a.paise)

  const executed = cases.filter((c) => c.executed).length
  const recovered = cases.filter((c) => c.recovered).length
  const blocked = cases.filter((c) => c.blocked).length
  const deferred = cases.filter((c) => c.deferred || c.scheduled).length

  const nextJob = status?.scheduler?.upcoming_jobs?.[0]

  return (
    <>
      <PageHeader
        title="Overview"
        lede={
          design
            ? `${design.treatment_n} customers see the agent, ${design.control_n} see the status quo. Model off. No live keys. n=${report.n}.`
            : `n=${report.n}.`
        }
      />
      <div className="quartet">
        <div className="stat">
          <p className="cap">At risk</p>
          <div className="n">{inr(report.at_risk_paise)}</div>
        </div>
        <div className="stat">
          <p className="cap">Treatment recovered</p>
          <div className="n">{inr(design?.treatment_recovered_paise ?? report.rekha_recovered_paise)}</div>
          <p className="sub">
            {design ? `${design.treatment_recoveries}/${design.treatment_n} · ${pct(report.treatment_rate ?? 0)}` : "n/a"}
          </p>
        </div>
        <div className="stat">
          <p className="cap">Control recovered</p>
          <div className="n">{inr(design?.control_recovered_paise ?? report.holdout_recovered_paise)}</div>
          <p className="sub">
            {design ? `${design.control_recoveries}/${design.control_n} · ${pct(report.control_rate ?? 0)}` : "n/a"}
          </p>
        </div>
        <div className="stat">
          <p className="cap">Incremental</p>
          <div className="n">{inrSigned(report.incremental_paise)}</div>
          <p className="sub">Rate CI excludes zero. Rupee BCa includes zero.</p>
        </div>
      </div>

      <div className="grid-2">
        <Panel title="Rate lift, Newcombe" lede="Treatment minus control recovery rate. This interval excludes zero.">
          <EstimatePlot
            obs={report.rate_lift_newcombe?.diff ?? 0}
            lo={report.rate_lift_newcombe?.lo ?? 0}
            hi={report.rate_lift_newcombe?.hi ?? 0}
            format={pp}
            caption={`${pp(report.rate_lift_newcombe?.diff ?? 0)} [${pp(report.rate_lift_newcombe?.lo ?? 0)}, ${pp(report.rate_lift_newcombe?.hi ?? 0)}]`}
          />
        </Panel>
        <Panel title="Rupee lift, BCa" lede="This interval includes zero. Do not treat rupees as a clean causal estimate.">
          <EstimatePlot
            obs={report.rupee_lift_bca?.obs ?? 0}
            lo={report.rupee_lift_bca?.lo ?? 0}
            hi={report.rupee_lift_bca?.hi ?? 0}
            format={inr}
            caption={`${inr(report.rupee_lift_bca?.obs ?? 0)} [${inr(report.rupee_lift_bca?.lo ?? 0)}, ${inr(report.rupee_lift_bca?.hi ?? 0)}]`}
          />
        </Panel>
      </div>

      <div className="grid-2">
        <Panel title="Batch composition" lede="Counts from this eval, not a conversion over time.">
          <FunnelChart
            stages={[
              { label: "Cases", n: cases.length },
              { label: "Executed", n: executed, note: `${blocked} blocked, ${deferred} deferred or scheduled` },
              { label: "Recovered", n: recovered },
            ]}
          />
        </Panel>
        <Panel title="Recovered by engine">
          <GroupedBars rows={bars} />
        </Panel>
      </div>

      <Panel title="Design" lede={design?.note}>
        <p>
          Assignment {design?.assignment || "amount-stratified"}. Paired Rekha {inr(report.rekha_recovered_paise)} vs
          holdout {inr(report.holdout_recovered_paise)} vs oracle {inr(report.oracle_recovered_paise)} (
          {pct(report.oracle_ceiling_pct)} of ceiling). Replay{" "}
          {report.replay_case_id ? <Link href={`/cases/${report.replay_case_id}`}>{report.replay_case_id}</Link> : "n/a"}.
        </p>
      </Panel>

      <Panel title="Honesty">
        <p>{report.mde_honesty?.note}</p>
        <p>
          {report.scheduled_note ||
            `${report.scheduled_cases ?? 0} case(s) scheduled or deferred. Quiet-hour DEFER is not recovered.`}
        </p>
        <p>
          Invariants{" "}
          <Badge tone={report.invariants_passed ? "positive" : "negative"}>
            {report.invariants_passed ? "pass" : "fail"}
          </Badge>
          {violations.length > 0 ? ` ${violations.map(([k, v]) => `${k}×${v}`).join(", ")}` : ", 0 violations"}
        </p>
      </Panel>

      <Panel title="Live now">
        <p>
          Ledger{" "}
          <Link href="/ledger">
            agent {inr(ledger?.agent_paise ?? 0)}, self-cure {inr(ledger?.self_cure_paise ?? 0)}, {ledger?.entries ?? 0}{" "}
            entries
          </Link>
          .{" "}
          {nextJob ? (
            <>
              Next job {nextJob.kind} on <Link href={`/cases/${nextJob.case_id}`}>{nextJob.case_id}</Link>.
            </>
          ) : (
            "No scheduled jobs."
          )}
        </p>
      </Panel>
    </>
  )
}
