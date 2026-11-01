import { randomUUID } from "node:crypto";
import { expect, test, type Page, type Response } from "@playwright/test";
import Decimal from "decimal.js";

// 此验收通过真实浏览器表单和 HTTP 契约写 PostgreSQL，不使用路由拦截或前端替身。
test("HTTP 创建交易日志后刷新和全新浏览器会话仍读取同一数据库记录", async ({ page, browser }) => {
  const backendUrl = process.env.HTTP_E2E_BACKEND_URL;
  if (backendUrl === undefined) throw new Error("HTTP E2E backend URL is missing");
  const label = `HTTP联验-${randomUUID()}`;
  const isTradeResponse = (response: Response, method: string) => {
    const url = new URL(response.url());
    return url.origin === backendUrl && url.pathname === "/api/v1/trades"
      && response.request().method() === method;
  };

  await page.goto("/trades/new");
  await expect(page.getByRole("heading", { name: "新增交易日志" })).toBeVisible();
  await page.getByLabel("标签").fill(label);
  await page.getByLabel("研究理由").fill("合成 HTTP 数据库持久化验收记录");
  const firstLeg = page.getByRole("group", { name: "交易腿 1" });
  await firstLeg.getByLabel("交易腿 ID").fill(randomUUID());
  await firstLeg.getByLabel("执行时间（UTC）").fill("2026-01-01T01:00:00Z");
  await firstLeg.getByLabel("价格").fill("100.10");
  await firstLeg.getByLabel("数量").fill("1.00");
  await firstLeg.getByLabel("手续费").fill("0.10");
  await page.getByRole("button", { name: "添加交易腿" }).click();
  const closeLeg = page.getByRole("group", { name: "交易腿 2" });
  await closeLeg.getByLabel("交易腿 ID").fill(randomUUID());
  await closeLeg.getByLabel("动作").selectOption("close");
  await closeLeg.getByLabel("执行时间（UTC）").fill("2026-01-01T02:00:00Z");
  await closeLeg.getByLabel("价格").fill("120.10");
  await closeLeg.getByLabel("数量").fill("1.00");
  await closeLeg.getByLabel("手续费").fill("0.20");

  const savedResponse = page.waitForResponse((response) => isTradeResponse(response, "POST"));
  await page.getByRole("button", { name: "保存交易日志" }).click();
  const saved = await savedResponse;
  expect(saved.status()).toBe(201);
  const savedTrade = await saved.json() as { id: string; labels: string[]; netPnl: string };
  expect(savedTrade.id).toMatch(/^[0-9a-f-]{36}$/);
  expect(savedTrade.labels).toEqual([label]);
  // PostgreSQL Numeric 保留固定精度，按 Decimal 比较金额，避免文本小数位误判。
  expect(new Decimal(savedTrade.netPnl).equals("19.7")).toBe(true);
  await expect(page.getByText("交易日志已保存。", { exact: true })).toBeVisible();

  async function assertPersisted(current: Page): Promise<void> {
    const listing = current.waitForResponse((response) => isTradeResponse(response, "GET"));
    await current.goto(`/trades?label=${encodeURIComponent(label)}`);
    const response = await listing;
    expect(response.status()).toBe(200);
    const payload = await response.json() as { items: Array<{ id: string; netPnl: string }> };
    const persisted = payload.items.find((trade) => trade.id === savedTrade.id);
    expect(persisted).toBeDefined();
    expect(new Decimal(persisted?.netPnl ?? "NaN").equals("19.7")).toBe(true);
    const row = current.getByRole("table", { name: "交易日志记录" }).getByRole("row").nth(1);
    await expect(current.getByLabel("标签")).toHaveValue(label);
    await expect(row).toContainText("BTCUSDT");
    await expect(row.getByRole("link", { name: "编辑日志" })).toHaveAttribute(
      "href", `/trades/${savedTrade.id}/edit`,
    );
  }

  await assertPersisted(page);
  const refreshed = page.waitForResponse((response) => isTradeResponse(response, "GET"));
  await page.reload();
  expect((await refreshed).status()).toBe(200);
  await expect(page.getByRole("table", { name: "交易日志记录" })).toContainText("BTCUSDT");
  await expect(page.getByLabel("标签")).toHaveValue(label);

  // 新建 context 不共享 localStorage 或 React Query 缓存，排除仅前端内存保留的假绿。
  const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    await assertPersisted(await context.newPage());
  } finally {
    await context.close();
  }
});
