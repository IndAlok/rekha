export function Banner({
  kind = "info",
  children,
}: {
  kind?: "info" | "warn" | "danger" | "ok"
  children: React.ReactNode
}) {
  const cls = kind === "info" ? "banner" : `banner ${kind}`
  return <div className={cls}>{children}</div>
}
