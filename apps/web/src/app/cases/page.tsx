"use client"

import Link from "next/link"
import { Suspense, useEffect, useMemo, useRef } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { EvalGate } from "@/components/EvalGate"
import { Badge } from "@/components/ui/Badge"
import { Pager, Table, Td, Th, Tr } from "@/components/ui/DataTable"
import { PageHeader } from "@/components/ui/PageHeader"
import { SegmentedControl } from "@/components/ui/SegmentedControl"
import { TableSkeleton } from "@/components/ui/Skeleton"
import { api, type CaseRow } from "@/lib/api"
import { useFetch } from "@/lib/useLoad"
import { inr } from "@/lib/format"

const PAGE = 25
type SortKey = "case_id" | "amount_paise" | "effect" | "engine"
type Rec = "all" | "yes" | "no"

function CasesInner() {
  const { data: rows, err, loading, reload } = useFetch((signal) => api.cases(signal))
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const searchRef = useRef<HTMLInputElement>(null)

  const q = params.get("q") || ""
  const engine = params.get("engine") || "all"
  const effect = params.get("effect") || "all"
  const recovered = (params.get("recovered") || "all") as Rec
  const sortKey = (params.get("sort") || "case_id") as SortKey
  const sortDir = params.get("dir") === "desc" ? "desc" : "asc"
  const page = Math.max(1, Number(params.get("page") || "1") || 1)

  const setParams = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params.toString())
    for (const [k, v] of Object.entries(patch)) {
      if (!v || v === "all" || (k === "page" && v === "1") || (k === "sort" && v === "case_id") || (k === "dir" && v === "asc")) {
        next.delete(k)
      } else {
        next.set(k, v)
      }
    }
    const qs = next.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const list = useMemo(() => rows || [], [rows])
  const engines = useMemo(
    () => Array.from(new Set(list.map((r) => r.proposal?.engine).filter(Boolean))) as string[],
    [list],
  )

  const shown = useMemo(() => {
    const filtered = list.filter((r) => {
      if (engine !== "all" && r.proposal?.engine !== engine) return false
      if (effect !== "all" && r.verdict?.effect !== effect) return false
      if (recovered === "yes" && !r.recovered) return false
      if (recovered === "no" && r.recovered) return false
      if (q && !`${r.case_id} ${r.trap || ""} ${r.diagnosis?.error_reason || ""}`.toLowerCase().includes(q.toLowerCase())) {
        return false
      }
      return true
    })
    const dir = sortDir === "asc" ? 1 : -1
    filtered.sort((a, b) => {
      if (sortKey === "amount_paise") return (a.amount_paise - b.amount_paise) * dir
      if (sortKey === "effect") return String(a.verdict?.effect || "").localeCompare(String(b.verdict?.effect || "")) * dir
      if (sortKey === "engine") return String(a.proposal?.engine || "").localeCompare(String(b.proposal?.engine || "")) * dir
      return a.case_id.localeCompare(b.case_id) * dir
    })
    return filtered
  }, [list, engine, effect, recovered, q, sortKey, sortDir])

  if (err) return <EvalGate error={err} onReady={reload} />

  const pages = Math.max(1, Math.ceil(shown.length / PAGE))
  const safePage = Math.min(page, pages)
  const slice = shown.slice((safePage - 1) * PAGE, safePage * PAGE)
  const toggle = (key: SortKey) =>
    setParams({ sort: key, dir: sortKey === key && sortDir === "asc" ? "desc" : "asc", page: "1" })

  return (
    <>
      <PageHeader title="Cases" lede={`${shown.length} of ${list.length} shown. Press / to search. Filters live in the URL.`} />
      <div className="filters">
        <input
          ref={searchRef}
          className="input"
          placeholder="Search id, trap, reason"
          value={q}
          onChange={(e) => setParams({ q: e.target.value, page: "1" })}
          aria-label="Search cases"
        />
        <select className="select" value={engine} onChange={(e) => setParams({ engine: e.target.value, page: "1" })} aria-label="Engine">
          <option value="all">All engines</option>
          {engines.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <select className="select" value={effect} onChange={(e) => setParams({ effect: e.target.value, page: "1" })} aria-label="Effect">
          <option value="all">All effects</option>
          <option value="ALLOW">ALLOW</option>
          <option value="DENY">DENY</option>
          <option value="DEFER">DEFER</option>
          <option value="REQUIRE_APPROVAL">REQUIRE_APPROVAL</option>
        </select>
        <SegmentedControl
          ariaLabel="Recovered filter"
          value={recovered}
          onChange={(v) => setParams({ recovered: v, page: "1" })}
          options={[
            { id: "all", label: "All" },
            { id: "yes", label: "Recovered" },
            { id: "no", label: "Not recovered" },
          ]}
        />
      </div>
      {loading ? (
        <TableSkeleton />
      ) : (
        <>
          <Table>
            <thead>
              <tr>
                <Th sort={() => toggle("case_id")} active={sortKey === "case_id"} dir={sortDir}>
                  id
                </Th>
                <th>class</th>
                <Th sort={() => toggle("engine")} active={sortKey === "engine"} dir={sortDir}>
                  engine
                </Th>
                <Th sort={() => toggle("effect")} active={sortKey === "effect"} dir={sortDir}>
                  effect
                </Th>
                <Th className="num" sort={() => toggle("amount_paise")} active={sortKey === "amount_paise"} dir={sortDir}>
                  amount
                </Th>
                <th>Rekha</th>
                <th>holdout</th>
                <th>trap</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <CaseLine key={r.case_id} row={r} />
              ))}
            </tbody>
          </Table>
          <Pager page={safePage} pages={pages} total={shown.length} onPage={(n) => setParams({ page: String(n) })} />
        </>
      )}
    </>
  )
}

function CaseLine({ row: r }: { row: CaseRow }) {
  return (
    <Tr>
      <Td>
        <Link className="mono" href={`/cases/${r.case_id}`}>
          {r.case_id}
        </Link>
      </Td>
      <Td>{r.diagnosis?.recoverability_class || ""}</Td>
      <Td>{r.proposal?.engine}</Td>
      <Td>
        <Badge>{r.verdict?.effect || "n/a"}</Badge>
      </Td>
      <Td className="num">{inr(r.amount_paise)}</Td>
      <Td>
        <span className="muted">{r.recovered ? "yes" : "no"}</span> {r.recovery_source}
      </Td>
      <Td className="muted">{r.holdout_recovered ? "yes" : "no"}</Td>
      <Td>{r.trap ? <Badge>{r.trap}</Badge> : ""}</Td>
    </Tr>
  )
}

export default function CasesPage() {
  return (
    <Suspense fallback={<TableSkeleton />}>
      <CasesInner />
    </Suspense>
  )
}
