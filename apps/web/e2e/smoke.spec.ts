import { expect, type Page, test } from "@playwright/test"

const OPS_TOKEN = "e2e-secret"
const API = "http://127.0.0.1:8080"

async function saveToken(page: Page) {
  await page.goto("/ops")
  await expect(page.getByRole("heading", { name: "Status" })).toBeVisible()
  await page.locator('input[type="password"]').fill(OPS_TOKEN)
  await page.getByRole("button", { name: "Save token" }).click()
  await expect(page.getByText("saved", { exact: true })).toBeVisible()
}

async function confirm(page: Page, arm: string, confirmLabel: string) {
  await page.getByRole("button", { name: arm, exact: true }).click()
  await page.getByRole("button", { name: confirmLabel }).click()
}

async function setKill(page: Page, engaged: boolean) {
  const res = await page.request.post(`${API}/kill-switch`, {
    headers: { "X-Ops-Token": OPS_TOKEN, "content-type": "application/json" },
    data: { engaged },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
}

async function sendWebhook(page: Page, sample: "failed" | "authorized") {
  await page.goto("/webhooks")
  await expect(page.getByRole("heading", { name: "Webhook console" })).toBeVisible()
  await page.getByRole("radio", { name: sample }).click()
  await expect(page.locator("textarea")).toContainText('"event"', { timeout: 10_000 })
  const sent = page.waitForResponse((r) => r.url().includes("/webhooks/razorpay") && r.request().method() === "POST")
  await page.getByRole("button", { name: "Send" }).click()
  await sent
  await expect(page.getByText(/ALLOW|DENY|DEFER|REQUIRE_APPROVAL|deduped|self_cure/).first()).toBeVisible({
    timeout: 20_000,
  })
}

test.beforeEach(async ({ page }) => {
  await setKill(page, false)
})

async function createVoiceApproval(page: Page) {
  await page.goto("/approvals")
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible()
  const created = page.waitForResponse((r) => r.url().includes("/cases/run") && r.request().method() === "POST")
  await page.getByRole("button", { name: "Run a ₹50,001 voice case" }).first().click()
  const res = await created
  expect(res.ok(), await res.text()).toBeTruthy()
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible({ timeout: 20_000 })
}

test("overview loads after boot eval", async ({ page }) => {
  await page.goto("/")
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText("At risk")).toBeVisible({ timeout: 90_000 })
  await expect(page.getByRole("link", { name: "Demo" })).toHaveCount(0)
})

test("demo route is gone", async ({ page }) => {
  await page.goto("/demo")
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible()
})

test("webhook failed then live case", async ({ page }) => {
  await sendWebhook(page, "failed")
  await page.goto("/live")
  await expect(page.getByRole("heading", { name: "Live cases" })).toBeVisible()
  await expect(page.locator("table.data")).toBeVisible()
})

test("authorized payment lands on ledger", async ({ page }) => {
  await sendWebhook(page, "failed")
  await sendWebhook(page, "authorized")
  await page.goto("/ledger")
  await expect(page.getByRole("heading", { name: "Ledger" })).toBeVisible()
  await expect(page.locator("table.data tbody tr").first()).toBeVisible({ timeout: 20_000 })
  await expect(page.locator("table.data .badge").first()).toHaveText(/self_cure|agent/)
})

test("status page shows env pills", async ({ page }) => {
  await page.goto("/ops")
  await expect(page.getByRole("heading", { name: "Status" })).toBeVisible()
  await expect(page.getByText(/Ops token/)).toBeVisible()
})

test("missing token prompts on mutating call", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.removeItem("rekha.opsToken"))
  await page.goto("/ops")
  await expect(page.getByRole("heading", { name: "Status" })).toBeVisible()
  await expect(page.getByText("clear", { exact: true })).toBeVisible({ timeout: 15_000 })
  await confirm(page, "Engage", "Engage it")
  await expect(page.getByText(/Ops token missing or wrong/)).toBeVisible({ timeout: 15_000 })
})

test("run 50001 voice, approve, then audit", async ({ page }) => {
  await saveToken(page)
  await createVoiceApproval(page)
  const decided = page.waitForResponse((r) => r.url().includes("/decide") && r.request().method() === "POST")
  await confirm(page, "Approve", "Approve and execute")
  const res = await decided
  expect(res.ok(), await res.text()).toBeTruthy()
  await page.goto("/audit")
  await expect(page.getByRole("heading", { name: "Audit chain" })).toBeVisible()
  await expect(page.locator("table.data tbody tr").first()).toBeVisible({ timeout: 15_000 })
})

test("kill switch blocks approve", async ({ page }) => {
  await saveToken(page)
  await createVoiceApproval(page)
  await setKill(page, true)
  await page.goto("/approvals")
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible({ timeout: 15_000 })
  const decided = page.waitForResponse((r) => r.url().includes("/decide") && r.request().method() === "POST")
  await confirm(page, "Approve", "Approve and execute")
  const res = await decided
  expect(res.status(), await res.text()).toBe(409)
  await expect(page.locator(".banner.danger")).toContainText("Kill switch is on", { timeout: 15_000 })
  await setKill(page, false)
})

test("tamper shows broken banner", async ({ page }) => {
  await saveToken(page)
  await sendWebhook(page, "failed")
  await page.goto("/audit")
  await expect(page.getByRole("heading", { name: "Audit chain" })).toBeVisible()
  await confirm(page, "Tamper one row", "This flips action on row 4 in memory")
  await expect(page.getByText(/broken/i).first()).toBeVisible({ timeout: 15_000 })
})
