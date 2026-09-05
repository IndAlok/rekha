import { render, screen } from "@testing-library/react"
import { describe, expect, test } from "vitest"
import { KeyVal } from "./KeyVal"

describe("KeyVal", () => {
  test("keeps 0 and false instead of n/a", () => {
    render(
      <KeyVal
        rows={[
          ["Touches", 0],
          ["Recovered", false],
          ["Empty", ""],
        ]}
      />,
    )
    expect(screen.getByText("0")).toBeInTheDocument()
    expect(screen.getByText("false")).toBeInTheDocument()
    expect(screen.getByText("n/a")).toBeInTheDocument()
  })
})
