import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

// 独立端口与模式，禁止复用业务服务或 Mock 验收服务。
function port(name: string, fallback: number): number {
  const value = process.env[name] ?? String(fallback);
  if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 65535) {
    throw new Error("HTTP E2E port configuration is invalid");
  }
  return Number(value);
}

const backendPort = port("HTTP_E2E_BACKEND_PORT", 8174);
const frontendPort = port("HTTP_E2E_FRONTEND_PORT", 4174);
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
// 主 runner 每次生成新 token，测试 worker 重载配置时必须继承它，避免与服务端失配。
// TEST_WORKER_INDEX 由 Playwright 在 worker 加载配置之前设置；token 不进入 VITE_*。
if (process.env.TEST_WORKER_INDEX === undefined) {
  process.env.HTTP_E2E_TOKEN = randomUUID();
}
process.env.HTTP_E2E_BACKEND_URL = backendUrl;
const token = process.env.HTTP_E2E_TOKEN;
if (token === undefined || token === "") {
  throw new Error("HTTP E2E run token is missing");
}
const python = process.env.HTTP_E2E_PYTHON;
if (python !== undefined && /["\r\n]/.test(python)) {
  throw new Error("HTTP E2E Python executable configuration is invalid");
}
const backendCommand = python === undefined
  ? "uv run --locked --no-sync python"
  : `"${python}"`;

export default defineConfig({
  testDir: "./e2e-http",
  globalTeardown: "./e2e-http/global-teardown.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"]],
  outputDir: "../.tmp/http-e2e/test-results",
  use: {
    baseURL: frontendUrl,
    viewport: { width: 1280, height: 900 },
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  webServer: [
    // 前端先启动：若 Vite 端口被占用，Windows 强制终止路径也不会留下数据库 schema。
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: frontendUrl,
      env: {
        VITE_DATA_MODE: "api",
        VITE_API_BASE_URL: backendUrl,
        VITE_MARKET_DATA_SOURCE: "live",
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `${backendCommand} -m scripts.http_e2e_server --port ${backendPort}`,
      cwd: resolve(process.cwd(), "../backend"),
      url: `${backendUrl}/__http_e2e__/ready`,
      env: { HTTP_E2E_TOKEN: token },
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
      timeout: 120_000,
    },
  ],
});
