const TONE: Record<string, string> = {
  ALLOW: "positive",
  recovered: "positive",
  agent: "positive",
  Kept: "positive",
  verified: "positive",
  DENY: "negative",
  blocked: "negative",
  Broken: "negative",
  broken: "negative",
  DEFER: "warning",
  scheduled: "warning",
  PartiallyKept: "warning",
  REQUIRE_APPROVAL: "info",
  Open: "info",
  Reminded: "info",
  self_cure: "info",
  live: "info",
  urgent: "urgent",
}

export function Badge({
  children,
  tone,
}: {
  children: React.ReactNode
  tone?: "neutral" | "positive" | "negative" | "warning" | "info" | "urgent"
}) {
  const key = String(children)
  const resolved = tone || TONE[key] || "neutral"
  return <span className={`badge badge-${resolved}`}>{children}</span>
}

export function effectTone(effect?: string) {
  return effect || "n/a"
}
