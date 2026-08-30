export function FunnelChart({
  stages,
}: {
  stages: Array<{ label: string; n: number; note?: string }>
}) {
  const max = Math.max(1, ...stages.map((s) => s.n))
  return (
    <div>
      {stages.map((s, i) => {
        const prev = i === 0 ? s.n : stages[i - 1].n
        const conv = prev ? Math.round((s.n / prev) * 100) : 0
        return (
          <div key={s.label} style={{ marginBottom: 10 }}>
            <div className="bar-row">
              <span>{s.label}</span>
              <div className="bar-track" aria-hidden>
                <div className="bar-fill" style={{ width: `${(s.n / max) * 100}%` }} />
              </div>
              <span className="tabular">{s.n}</span>
            </div>
            {i > 0 ? <div className="faint">{conv}% of previous stage</div> : null}
            {s.note ? <div className="muted">{s.note}</div> : null}
          </div>
        )
      })}
      <p className="lede">This eval batch, not a time funnel.</p>
      <p className="sr-only">
        {stages.map((s) => `${s.label} ${s.n}`).join(", ")}
      </p>
    </div>
  )
}
