function cell(v: React.ReactNode) {
  if (v === false) return "false"
  if (v === true) return "true"
  if (v === 0) return 0
  if (v == null || v === "") return "n/a"
  return v
}

export function KeyVal({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{cell(v)}</dd>
        </div>
      ))}
    </dl>
  )
}
