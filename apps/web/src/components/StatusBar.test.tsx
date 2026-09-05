import { render, screen } from "@testing-library/react"
import { describe, expect, test } from "vitest"
import { StatusBar } from "./StatusBar"

describe("StatusBar", () => {
  test("shows advisor off when the key is missing", () => {
    render(
      <StatusBar
        phase="up"
        status={{
          ok: true,
          eval_ready: true,
          kill_switch: false,
          advisor: { configured: false, provider: "off", eval: "off", live_only: true },
        }}
      />,
    )
    expect(screen.getByText("advisor off")).toBeInTheDocument()
    expect(screen.getByText("eval ready")).toBeInTheDocument()
  })

  test("shows groq without a key", () => {
    render(
      <StatusBar
        phase="up"
        status={{
          ok: true,
          eval_ready: true,
          kill_switch: false,
          advisor: { configured: true, provider: "groq", model: "llama-3.3-70b-versatile", eval: "off", live_only: true },
        }}
      />,
    )
    expect(screen.getByText("advisor groq")).toBeInTheDocument()
    expect(screen.queryByText(/gsk_/)).toBeNull()
  })
})
