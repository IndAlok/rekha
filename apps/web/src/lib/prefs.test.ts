import { describe, expect, test } from "vitest"
import { maskValue, redact } from "./prefs"

describe("maskValue", () => {
  test("keeps last two of last4", () => {
    expect(maskValue("last4", "4242")).toBe("••42")
  })
  test("masks a phone", () => {
    expect(maskValue("contact", "+919800000001")).toMatch(/^\+91/)
    expect(String(maskValue("contact", "+919800000001"))).toContain("••••")
  })
})

describe("redact", () => {
  test("walks nested objects", () => {
    const out = redact({ last4: "4242", inner: { contact: "+9198" } }, true) as { last4: string; inner: { contact: string } }
    expect(out.last4).toBe("••42")
    expect(out.inner.contact).toContain("••••")
  })
  test("off leaves values", () => {
    expect(redact({ last4: "4242" }, false)).toEqual({ last4: "4242" })
  })
  test("masks last_name", () => {
    const out = redact({ last_name: "Sharma", first_name: "Riya" }, true) as { last_name: string; first_name: string }
    expect(out.last_name).toContain("••••")
    expect(out.first_name).toContain("••••")
  })
})
