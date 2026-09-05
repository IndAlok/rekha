import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, test, vi } from "vitest"
import { ConfirmButton } from "./ConfirmButton"

describe("ConfirmButton", () => {
  test("disarms after confirm even when onConfirm throws", async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn(async () => {
      throw new Error("nope")
    })
    render(<ConfirmButton onConfirm={onConfirm}>Do</ConfirmButton>)
    await user.click(screen.getByRole("button", { name: "Do" }))
    await user.click(screen.getByRole("button", { name: "Confirm" }))
    expect(await screen.findByRole("button", { name: "Do" })).toBeInTheDocument()
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  test("Escape disarms", async () => {
    const user = userEvent.setup()
    render(<ConfirmButton onConfirm={vi.fn()}>Arm</ConfirmButton>)
    await user.click(screen.getByRole("button", { name: "Arm" }))
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument()
    await user.keyboard("{Escape}")
    expect(screen.getByRole("button", { name: "Arm" })).toBeInTheDocument()
  })
})

