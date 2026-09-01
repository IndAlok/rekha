export function inr(paise: number): string {
  const n = Number.isFinite(paise) ? paise : 0
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n / 100)
}

export function inrSigned(paise: number): string {
  const n = Number.isFinite(paise) ? paise : 0
  const body = inr(Math.abs(n))
  if (n > 0) return `+${body}`
  if (n < 0) return `-${body}`
  return body
}

export function inrCompact(paise: number): string {
  const n = Number.isFinite(paise) ? paise : 0
  const rupees = Math.abs(n) / 100
  const sign = n < 0 ? "-" : ""
  if (rupees >= 1e7) {
    const v = rupees / 1e7
    return `${sign}₹${v.toFixed(v >= 10 ? 0 : 1).replace(/\.0$/, "")}Cr`
  }
  if (rupees >= 1e5) {
    const v = rupees / 1e5
    return `${sign}₹${v.toFixed(v >= 10 ? 0 : 1).replace(/\.0$/, "")}L`
  }
  if (rupees >= 1e3) {
    return `${sign}₹${Math.round(rupees / 1e3)}K`
  }
  return inr(n)
}

export function pct(value: number, digits = 1): string {
  const n = Number.isFinite(value) ? value : 0
  return `${(n * 100).toFixed(digits)}%`
}

export function pp(value: number, digits = 1): string {
  const n = Number.isFinite(value) ? value : 0
  const body = `${(n * 100).toFixed(digits)}pp`
  return n > 0 ? `+${body}` : body
}

export function dt(iso: string | null | undefined): string {
  if (!iso) return "n/a"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "n/a"
  const stamp = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d)
  return `${stamp} IST`
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "n/a"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "n/a"
  const seconds = Math.round((Date.now() - d.getTime()) / 1000)
  if (seconds < 60) return `${Math.max(0, seconds)}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return dt(iso)
}

export function hashShort(value: string | null | undefined): string {
  if (!value) return ""
  const h = String(value)
  if (h.length <= 12) return h
  return `0x${h.slice(0, 4)}..${h.slice(-2)}`
}

export function mark(ok: boolean): string {
  return ok ? "yes" : "no"
}
