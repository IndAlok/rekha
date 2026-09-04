const TOKEN_KEY = "rekha.opsToken"
const PII_KEY = "rekha.maskPii"

export function getOpsToken(): string {
  if (typeof window === "undefined") return ""
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ""
  } catch {
    return ""
  }
}

export function setOpsToken(token: string): void {
  if (typeof window === "undefined") return
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token)
    else window.localStorage.removeItem(TOKEN_KEY)
    window.dispatchEvent(new Event("rekha:prefs"))
  } catch {
    /* private mode */
  }
}

export function getMaskPii(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(PII_KEY) === "1"
  } catch {
    return false
  }
}

export function setMaskPii(on: boolean): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(PII_KEY, on ? "1" : "0")
    window.dispatchEvent(new Event("rekha:prefs"))
  } catch {
    /* private mode */
  }
}

const PII_KEYS = new Set(["contact", "phone", "email", "last4", "first_name", "last_name", "name", "vpa", "mobile"])

export function maskValue(key: string, value: unknown): unknown {
  if (!PII_KEYS.has(key) || value == null) return value
  const s = String(value)
  if (key === "last4") return s.length <= 2 ? "••••" : `••${s.slice(-2)}`
  if (s.length <= 4) return "••••"
  return `${s.slice(0, 3)}••••${s.slice(-2)}`
}

export function redact(value: unknown, on: boolean): unknown {
  if (!on || value == null) return value
  if (Array.isArray(value)) return value.map((row) => redact(row, true))
  if (typeof value !== "object") return value
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = PII_KEYS.has(k) ? maskValue(k, v) : redact(v, true)
  }
  return out
}
