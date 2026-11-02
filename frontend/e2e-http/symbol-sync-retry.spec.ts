import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  researchSymbolListSchema,
  researchSymbolSyncRunSchema,
} from "../src/domain/research-symbol";

// 只替换后端采集输入；浏览器通过生产路由/worker/SQL 完成人工重试，不拦截 HTTP。
async function readEntry(client: APIRequestContext, backendUrl: string, symbol: string) {
  const response = await client.get(`${backendUrl}/api/v1/research-symbols`);
  expect(response.status()).toBe(200);
  const entry = researchSymbolListSchema.parse(await response.json()).items.find(
    (item) => item.symbol === symbol,
  );
  if (entry === undefined) throw new Error("Synthetic research symbol is missing");
  return entry;
}

for (const scenario of [
  { symbol: "SOLUSDT", terminal: "partial", label: "部分覆盖", canResearch: true },
  { symbol: "XRPUSDT", terminal: "failed", label: "失败", canResearch: false },
]) {
  test(`同步 ${scenario.symbol} 失败后手动重试并持久化 ${scenario.terminal}`, async ({ page, browser }) => {
    const backendUrl = process.env.HTTP_E2E_BACKEND_URL;
    const token = process.env.HTTP_E2E_TOKEN;
    if (backendUrl === undefined || token === undefined) {
      throw new Error("HTTP E2E run configuration is missing");
    }
    const initial = await readEntry(page.request, backendUrl, scenario.symbol);
    expect(initial.canResearch).toBe(false);
    expect(initial.lastSync?.status).toBe("failed");
    const original = researchSymbolSyncRunSchema.parse(initial.lastSync);
    const path = `/api/v1/research-symbols/${scenario.symbol}/sync/retry`;
    await page.goto("/research-symbols");
    const card = page.getByRole("article", { name: scenario.symbol, exact: true });
    const retryButton = card.getByRole("button", { name: "重试同步", exact: true });
    await expect(card.getByText("最近同步：失败", { exact: true })).toBeVisible();
    await expect(retryButton).toBeEnabled();

    const enqueue = page.waitForResponse((response) => response.url() === `${backendUrl}${path}`
      && response.request().method() === "POST");
    // 事件门在 running 后保持采集阻塞；缺少目录轮询时，本断言会超时而不是碰巧通过。
    const runningRead = page.waitForResponse(async (response) => {
      if (response.url() !== `${backendUrl}/api/v1/research-symbols`
        || response.request().method() !== "GET" || response.status() !== 200) return false;
      return researchSymbolListSchema.parse(await response.json()).items.some(
        (item) => item.symbol === scenario.symbol && item.lastSync?.status === "running",
      );
    });
    await retryButton.click();
    const accepted = await enqueue;
    expect(accepted.status()).toBe(202);
    expect(accepted.request().postDataJSON()).toEqual({ runId: original.id });
    const run = researchSymbolSyncRunSchema.parse(await accepted.json());
    expect(run.status).toBe("queued");
    expect(run.symbol).toBe(scenario.symbol);
    expect(run.id).not.toBe(original.id);
    await runningRead;
    await expect(card.getByText("最近同步：运行中", { exact: true })).toBeVisible();
    await expect(retryButton).toBeDisabled();
    await expect(card.getByText("暂不可研究", { exact: true })).toBeVisible();

    const replay = await page.request.post(`${backendUrl}${path}`, { data: { runId: original.id } });
    expect(replay.status()).toBe(202);
    expect(researchSymbolSyncRunSchema.parse(await replay.json()).id).toBe(run.id);
    // token 只用于 runner 的控制请求，不放入浏览器存储或 VITE_* 配置。
    const released = await page.request.post(`${backendUrl}/__http_e2e__/symbol-sync/${scenario.symbol}/release`, {
      headers: { "x-http-e2e-token": token },
    });
    expect(released.status()).toBe(204);
    await expect(card.getByText(`最近同步：${scenario.label}`, { exact: true })).toBeVisible();
    await expect(card.getByText(scenario.canResearch ? "可研究" : "暂不可研究", { exact: true })).toBeVisible();
    if (scenario.canResearch) await expect(retryButton).toHaveCount(0);
    else await expect(retryButton).toBeEnabled();

    const saved = await readEntry(page.request, backendUrl, scenario.symbol);
    const terminal = researchSymbolSyncRunSchema.parse(saved.lastSync);
    expect(terminal.id).toBe(run.id);
    expect(terminal.status).toBe(scenario.terminal);
    expect(saved.canResearch).toBe(scenario.canResearch);
    expect(terminal.completedAt).not.toBeNull();
    expect(terminal.leaseToken).toBeNull();
    expect(JSON.stringify(saved)).not.toContain("OFFLINE_PRIVATE");
    if (scenario.canResearch) {
      expect(terminal.snapshotId).not.toBeNull();
      expect(terminal.sources.find((source) => source.name === "funding")?.status).toBe("missing");
    } else {
      expect(terminal.snapshotId).toBeNull();
      expect(terminal.error).toBe("market_sync_failed");
    }
    const stale = await page.request.post(`${backendUrl}${path}`, { data: { runId: original.id } });
    expect(stale.status()).toBe(409);
    expect(await stale.json()).toMatchObject({ code: "research_symbol_sync_retry_conflict" });

    await page.reload();
    await expect(card.getByText(`最近同步：${scenario.label}`, { exact: true })).toBeVisible();
    const fresh = await browser.newContext({ baseURL: new URL(page.url()).origin });
    try {
      const cleanPage = await fresh.newPage();
      await cleanPage.goto("/research-symbols");
      const cleanCard = cleanPage.getByRole("article", { name: scenario.symbol, exact: true });
      await expect(cleanCard.getByText(`最近同步：${scenario.label}`, { exact: true })).toBeVisible();
      await expect(cleanCard.getByText(scenario.canResearch ? "可研究" : "暂不可研究", { exact: true })).toBeVisible();
      expect(await readEntry(fresh.request, backendUrl, scenario.symbol)).toEqual(saved);
      await expect(cleanPage.getByText(/Mock 演示数据|OFFLINE_PRIVATE/)).toHaveCount(0);
    } finally {
      await fresh.close();
    }
  });
}
