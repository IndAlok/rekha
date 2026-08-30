export function Timeline({
  steps,
}: {
  steps: Array<{ title: string; body?: React.ReactNode; extra?: React.ReactNode }>
}) {
  return (
    <ol className="timeline">
      {steps.map((s) => (
        <li key={s.title}>
          <strong>{s.title}</strong>
          {s.body ? <div className="meta">{s.body}</div> : null}
          {s.extra}
        </li>
      ))}
    </ol>
  )
}
