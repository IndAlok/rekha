export function Banner({
  kind = "info",
  children,
}: {
  kind?: "info" | "warn" | "danger" | "ok"
  children: React.ReactNode
}) {
  const cls = kind === "info" ? "banner" : `banner ${kind}`
  const role = kind === "danger" || kind === "warn" ? "alert" : "status"
  return (
    <div className={cls} role={role}>
      {children}
    </div>
  )
}
