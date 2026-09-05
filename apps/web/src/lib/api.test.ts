import { describe, expect, test } from "vitest"
import { ApiError, parseError } from "./api"

describe("parseError", () => {
  test("401 with detail.code is UNAUTHORIZED", async () => {
    const res = new Response(JSON.stringify({ detail: { code: "UNAUTHORIZED", message: "valid X-Ops-Token required" } }), {
      status: 401,
      headers: { "content-type": "application/json" },
    })
    const err = await parseError(res)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe("UNAUTHORIZED")
    expect(err.status).toBe(401)
    expect(err.message).toMatch(/token/i)
  })

  test("409 kill switch keeps code", async () => {
    const res = new Response(JSON.stringify({ detail: { code: "KILL_SWITCH", message: "kill switch is engaged" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    })
    const err = await parseError(res)
    expect(err.code).toBe("KILL_SWITCH")
  })

  test("409 policy changed keeps code", async () => {
    const res = new Response(JSON.stringify({ detail: { code: "POLICY_CHANGED", message: "CONSENT_REVOKED" } }), {
      status: 409,
      headers: { "content-type": "application/json" },
    })
    const err = await parseError(res)
    expect(err.code).toBe("POLICY_CHANGED")
  })

  test("nested error.code from a proxy 500", async () => {
    const res = new Response(JSON.stringify({ error: { code: "INTERNAL_ERROR", message: "Function timed out" } }), {
      status: 500,
      headers: { "content-type": "application/json" },
    })
    const err = await parseError(res)
    expect(err.code).toBe("INTERNAL_ERROR")
    expect(err.message).toMatch(/timed out/i)
  })
})
