import { inrCompact } from "@/lib/format"

export function GroupedBars({ rows }: { rows: Array<{ label: string; paise: number }> }) {
  const max = Math.max(1, ...rows.map((r) => r.paise))
  if (rows.length === 0) return <p className="muted">No recovered rupees by engine in this batch.</p>
  return (
    <div>
      {rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <span>{r.label || "none"}</span>
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${(r.paise / max) * 100}%` }} />
          </div>
          <span className="num tabular">{inrCompact(r.paise)}</span>
        </div>
      ))}
      <p className="sr-only">
        {rows.map((r) => `${r.label} ${inrCompact(r.paise)}`).join(", ")}
      </p>
    </div>
  )
}
