export function Transcript({
  turns,
}: {
  turns: Array<{ state: string; agent: string; user: string | null; tool: string | null }>
}) {
  return (
    <div>
      {turns.map((t, i) => (
        <div key={i} className="bubble">
          <div className="who">
            {t.user ? "Caller" : "Asha"} · {t.state}
          </div>
          <div>{t.user ?? t.agent}</div>
          {t.tool ? <div className="muted">tool {t.tool}</div> : null}
        </div>
      ))}
    </div>
  )
}
