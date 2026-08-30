import path from "node:path"
import { defineConfig, devices } from "@playwright/test"

const root = path.resolve(__dirname, "../..")
const py = process.env.CI ? "python" : path.join(root, ".venv/bin/python")

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${py} -m uvicorn rekha.api:app --host 127.0.0.1 --port 8080`,
      cwd: root,
      url: "http://127.0.0.1:8080/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        PYTHONPATH: path.join(root, "apps/api"),
        REKHA_ENV: "dev",
        OPS_TOKEN: "e2e-secret",
      },
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { ...process.env, NEXT_PUBLIC_API_URL: "/api", API_UPSTREAM: "http://127.0.0.1:8080" },
    },
  ],
})
