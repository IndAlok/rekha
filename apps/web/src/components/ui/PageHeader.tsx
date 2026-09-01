export function PageHeader({
  title,
  lede,
  actions,
}: {
  title: string
  lede?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {lede ? <p className="lede">{lede}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  )
}
