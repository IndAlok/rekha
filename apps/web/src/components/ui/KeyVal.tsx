export function KeyVal({ rows }: { rows: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v || "n/a"}</dd>
        </div>
      ))}
    </dl>
  )
}
