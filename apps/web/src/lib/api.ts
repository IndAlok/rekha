import { inr } from "./format"
import { getOpsToken } from "./prefs"

export type Report = {
  n: number
  at_risk_paise: number
  rekha_recovered_paise: number
  holdout_recovered_paise: number
  oracle_recovered_paise: number
  incremental_paise: number
  incremental_scope?: string
  rekha_rate: number
  holdout_rate: number
  treatment_rate?: number
  control_rate?: number
  scheduled_cases?: number
  scheduled_note?: string
  design?: {
    primary: string
    assignment?: string
    treatment_n: number
    control_n: number
    treatment_recovered_paise: number
    control_recovered_paise: number
    treatment_recoveries: number
    control_recoveries: number
    note: string
  }
  rekha_rate_wilson: [number, number]
  rate_lift_newcombe: { diff: number; lo: number; hi: number }
  rupee_lift_bca: { obs: number; lo: number; hi: number }
  oracle_ceiling_pct: number
  invariants_passed: boolean
  violation_counts: Record<string, number>
  mde_honesty: { note: string }
  engines: Record<string, number>
  blocked_actions: Array<Record<string, unknown>>
  replay_case_id: string
}

export type CaseRow = {
  case_id: string
  source?: string
  strategy: string
  recovered: boolean
  recovery_source: string
  amount_paise: number
  blocked: boolean
  deferred: boolean
  scheduled?: boolean
  executed?: boolean
  violations: string[]
  proposal: { action?: string; engine?: string; channel?: string; reason?: string }
  verdict: { effect?: string; reason_code?: string; matched_rules?: unknown[]; policy_version?: string; policy_hash?: string }
  diagnosis: { recoverability_class?: string; error_reason?: string }
  trap?: string
  holdout_recovered?: boolean
  loss_class?: string
  experiment_arm?: string
  status?: string
  touches?: number
  updated_at?: string
  stop_reason?: string | null
  ledger?: LedgerRow[]
  audit?: Array<Record<string, unknown>>
}

export type LiveCase = {
  case_id: string
  status: string
  loss_class: string
  amount_paise: number
  touches: number
  recovered: boolean
  recovery_source: string
  stop_reason: string | null
  updated_at: string | null
}

export type Status = {
  ok: boolean
  eval_ready: boolean
  kill_switch: boolean
  live_audit_rows?: number
  scheduler?: { up: boolean; upcoming_jobs: Array<{ id: number; kind: string; case_id: string; run_at: string; status?: string }> }
  env?: string
  ops_auth_required?: boolean
  webhook_secret_set?: boolean
  payments_adapter?: string
  payments_adapter_effective?: string
  payments_fallback?: boolean
  payments_error?: string | null
  boot_ok?: boolean
  boot_errors?: string[]
  whatsapp_quality?: string
  database?: string
  degradation?: Array<Record<string, unknown>>
}

export type Approval = {
  id: string
  case_id: string
  status?: string
  approver_role: string
  amount_paise: number
  expires_at: string
  decided_at?: string | null
  proposal: { action?: string; channel?: string; reason?: string }
}

export type Job = {
  id: number
  kind: string
  case_id: string
  run_at: string
  attempts: number
  status: string
  lease_expires_at?: string | null
}

export type PolicyDoc = {
  version: string
  policy_hash: string
  rules: Array<Record<string, unknown>>
  constants: Record<string, unknown>
  caps: Record<string, unknown>
  blocked_counts: Record<string, number>
}

export type AwaazSession = {
  case_id: string
  verified: boolean
  stopped: boolean
  stop_reason: string | null
  compliance_flags: string[]
  captured_ptp: { date: string; amount_paise: number } | null
  turns: Array<{ state: string; agent: string; user: string | null; tool: string | null }>
}

export type LedgerRow = {
  case_id: string
  action: string | null
  channel: string | null
  source_event: string
  amount_paise: number
  attribution: string
  recovered_at: string
}

export type InboxRow = {
  event_id: string
  event_type: string
  processed: boolean
  received_at: string | null
  error_text?: string | null
}

export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

function loopback(url: string): boolean {
  return /127\.0\.0\.1|localhost/.test(url)
}

function base(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_API_URL || "").trim()
  if (fromEnv.startsWith("/")) return fromEnv.replace(/\/$/, "") || "/api"
  if (fromEnv && typeof window !== "undefined") {
    const pageHost = window.location.hostname
    const pageIsLoopback = pageHost === "localhost" || pageHost === "127.0.0.1"
    if (loopback(fromEnv) && !pageIsLoopback) return "/api"
    return fromEnv.replace(/\/$/, "")
  }
  if (fromEnv) return fromEnv.replace(/\/$/, "")
  return "/api"
}

function timeoutMs(path: string): number {
  return path.startsWith("/eval/run") ? 120_000 : 20_000
}

function mergeSignals(a?: AbortSignal, b?: AbortSignal): AbortSignal | undefined {
  if (a && b && typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function") {
    return AbortSignal.any([a, b])
  }
  return a || b
}

function notifyUnauthorized() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("rekha:unauthorized"))
  }
}

export async function parseError(res: Response): Promise<ApiError> {
  if (res.status === 401) notifyUnauthorized()
  try {
    const body = await res.json()
    const detail = body.detail
    if (detail && typeof detail === "object" && detail.code) {
      return new ApiError(String(detail.code), String(detail.message || detail.code), res.status)
    }
    if (typeof detail === "string") {
      return new ApiError(res.status === 404 ? "NOT_FOUND" : "HTTP_ERROR", detail, res.status)
    }
  } catch {
    /* body was not json */
  }
  if (res.status === 503 || res.status === 502) {
    return new ApiError("API_UNREACHABLE", "The API is not reachable from this page", res.status)
  }
  if (res.status === 401) return new ApiError("UNAUTHORIZED", "Ops token missing or wrong", 401)
  if (res.status === 409) return new ApiError("CONFLICT", `HTTP ${res.status}`, 409)
  if (res.status === 404) return new ApiError("NOT_FOUND", "Not found", 404)
  return new ApiError("HTTP_ERROR", `HTTP ${res.status}`, res.status)
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getOpsToken()
  const headers: Record<string, string> = { ...(extra || {}) }
  if (token) headers["X-Ops-Token"] = token
  return headers
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${base()}${path}`, {
      cache: "no-store",
      signal: mergeSignals(signal, AbortSignal.timeout(timeoutMs(path))),
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e
    throw new ApiError("API_UNREACHABLE", "The API is not reachable from this page")
  }
  if (!res.ok) throw await parseError(res)
  return res.json()
}

async function mutate<T>(method: string, path: string, body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${base()}${path}`, {
      method,
      headers: authHeaders({ "content-type": "application/json", ...(extraHeaders || {}) }),
      body: body === undefined ? "{}" : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs(path)),
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e
    throw new ApiError("API_UNREACHABLE", "The API is not reachable from this page")
  }
  if (!res.ok) throw await parseError(res)
  return res.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return mutate<T>("POST", path, body)
}

export const api = {
  status: (signal?: AbortSignal) => get<Status>("/status", signal),
  report: (signal?: AbortSignal) => get<Report>("/eval/latest", signal),
  cases: (opts?: { trap?: string | null; blocked?: boolean; signal?: AbortSignal }) => {
    const q = new URLSearchParams()
    if (opts?.trap) q.set("trap", opts.trap)
    if (opts?.blocked) q.set("blocked", "true")
    const qs = q.toString()
    return get<CaseRow[]>(`/cases${qs ? `?${qs}` : ""}`, opts?.signal)
  },
  case: (id: string, signal?: AbortSignal) => get<CaseRow>(`/cases/${encodeURIComponent(id)}`, signal),
  neighbors: (id: string, signal?: AbortSignal) =>
    get<{ prev: string | null; next: string | null }>(`/cases/${encodeURIComponent(id)}/neighbors`, signal),
  liveCases: (signal?: AbortSignal) => get<LiveCase[]>("/cases/live", signal),
  blocked: (signal?: AbortSignal) => get<Report["blocked_actions"]>("/compliance/blocked", signal),
  ptp: (signal?: AbortSignal) => get<Array<Record<string, unknown>>>("/ptp", signal),
  audit: (signal?: AbortSignal) =>
    get<{ ok: boolean; msg: string; rows: Array<Record<string, unknown>>; source?: string }>("/audit", signal),
  verify: () => post<{ ok: boolean; msg: string; rows: number }>("/audit/verify"),
  tamper: () => post<{ ok: boolean; msg: string; tampered_seq: number }>("/audit/tamper"),
  kill: (engaged: boolean) => post<{ kill_switch: boolean; persisted?: boolean }>("/kill-switch", { engaged }),
  runEval: (seed = 42) => post<Report>(`/eval/run?seed=${seed}`),
  runCase: (body: { case_id?: string; case?: Record<string, unknown> }) =>
    post<CaseRow & { approval_id?: string }>("/cases/run", body),
  approvals: (status = "pending", signal?: AbortSignal) =>
    get<Approval[]>(`/approvals?status=${encodeURIComponent(status)}`, signal),
  decideApproval: (id: string, decision: "approve" | "reject") =>
    post<{ ok: boolean; status: string }>(`/approvals/${encodeURIComponent(id)}/decide`, { decision, approver: "dashboard" }),
  ledger: (attribution?: string, signal?: AbortSignal) => {
    const q = attribution && attribution !== "all" ? `?attribution=${encodeURIComponent(attribution)}` : ""
    return get<{ totals: { agent_paise: number; self_cure_paise: number; entries: number }; rows: LedgerRow[] }>(
      `/ledger${q}`,
      signal,
    )
  },
  sampleWebhook: (name = "payment_failed", signal?: AbortSignal) =>
    get<Record<string, unknown>>(`/webhooks/sample?name=${encodeURIComponent(name)}`, signal),
  recentWebhooks: (limit = 15, signal?: AbortSignal) => get<{ rows: InboxRow[] }>(`/webhooks/recent?limit=${limit}`, signal),
  awaaz: (cse: Record<string, unknown>, lines: string[]) => post<AwaazSession>("/awaaz/session", { case: cse, lines }),
  policy: (signal?: AbortSignal) => get<PolicyDoc>("/policy", signal),
  jobs: (status?: string, signal?: AbortSignal) => {
    const q = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : ""
    return get<{ jobs: Job[] }>(`/jobs${q}`, signal)
  },
  cancelJob: (id: number) => post<{ id: number; cancelled?: boolean; status?: string }>(`/jobs/${id}/cancel`),
  complaints: (customerId?: string, signal?: AbortSignal) => {
    const q = customerId ? `?customer_id=${encodeURIComponent(customerId)}` : ""
    return get<Record<string, unknown>>(`/complaints/state${q}`, signal)
  },
  fileComplaint: (customerId: string) => post<{ ok: boolean; throttled: boolean }>("/complaints", { customer_id: customerId }),
  customer: (id: string, signal?: AbortSignal) => get<Record<string, unknown>>(`/customers/${encodeURIComponent(id)}`, signal),
  setConsent: (id: string, status: "GRANTED" | "REVOKED" | "UNKNOWN") =>
    post<Record<string, unknown>>(`/customers/${encodeURIComponent(id)}/consent`, { status }),
  setCustomerFlags: (id: string, flags: { dnd?: boolean; legal_hold?: boolean; opt_out?: boolean }) =>
    post<Record<string, unknown>>(`/ops/customers/${encodeURIComponent(id)}/flags`, flags),
  setWhatsappQuality: (quality: "green" | "yellow" | "red") =>
    post<{ whatsapp_quality: string; persisted?: boolean }>("/ops/whatsapp-quality", { quality }),
  signWebhook: (payload: unknown) => post<{ signature: string }>("/webhooks/sign", payload),
  webhook: async (payload: unknown, eventId?: string, signature?: string) => {
    let sig = signature?.trim() || ""
    if (!sig && getOpsToken()) {
      try {
        sig = (await post<{ signature: string }>("/webhooks/sign", payload)).signature
      } catch (e) {
        if (!(e instanceof ApiError && e.code === "SECRET_UNSET")) throw e
      }
    }
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "X-Razorpay-Event-Id": eventId || `sim-${Date.now()}`,
    }
    if (sig) headers["X-Razorpay-Signature"] = sig
    let res: Response
    try {
      res = await fetch(`${base()}/webhooks/razorpay?wait=true`, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(20_000),
      })
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e
      throw new ApiError("API_UNREACHABLE", "The API is not reachable from this page")
    }
    if (!res.ok) throw await parseError(res)
    return res.json()
  },
}

export { inr }
