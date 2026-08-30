export function Panel({
  title,
  lede,
  actions,
  children,
}: {
  title?: string
  lede?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <div className="panel-h">
          <div>
            {title ? <h2>{title}</h2> : null}
            {lede ? <p className="lede">{lede}</p> : null}
          </div>
          {actions}
        </div>
      )}
      <div className="panel-b">{children}</div>
    </section>
  )
}
