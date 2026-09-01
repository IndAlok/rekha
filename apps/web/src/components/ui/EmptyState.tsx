export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: React.ReactNode
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action ? <div style={{ marginTop: 12 }}>{action}</div> : null}
    </div>
  )
}
