import { describe, expect, test } from "vitest"
import { inr, inrCompact, inrSigned, pct, pp } from "./format"

describe("inrCompact", () => {
  test("uses 0 fraction digits at 10 Cr and above", () => {
    expect(inrCompact(10_00_00_000_00)).toMatch(/₹10Cr/)
  })
  test("keeps one fraction digit below 10 L", () => {
    expect(inrCompact(1_50_000_00)).toMatch(/₹1\.5L/)
  })
  test("thousands become K", () => {
    expect(inrCompact(12_400_00)).toMatch(/₹12K/)
  })
})

describe("inr", () => {
  test("formats paise as rupees", () => {
    expect(inr(129900)).toMatch(/1,299/)
  })
  test("signed prefix", () => {
    expect(inrSigned(100)).toMatch(/^\+/)
    expect(inrSigned(-100)).toMatch(/^-/)
  })
})

describe("pct", () => {
  test("rate and percentage points", () => {
    expect(pct(0.312)).toBe("31.2%")
    expect(pp(0.312)).toBe("+31.2pp")
  })
})
