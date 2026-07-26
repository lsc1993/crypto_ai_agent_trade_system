import { defineConfig } from "@playwright/test";

const baseUrl = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI === undefined ? 0 : 1,
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  preserveOutput: "always",
  use: {
    baseURL: baseUrl,
    screenshot: "on",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-1280",
      use: { viewport: { width: 1280, height: 900 } },
    },
    {
      name: "desktop-1440",
      use: { viewport: { width: 1440, height: 960 } },
    },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4173",
    url: baseUrl,
    reuseExistingServer: process.env.CI === undefined,
    timeout: 120_000,
  },
});
