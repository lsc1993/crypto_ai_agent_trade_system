import { expect, test } from "@playwright/test";

// 两条路径均走实际路由、队列、worker、Harness 和 PostgreSQL；浏览器不拦截请求。
for (const scenario of [
  { symbol: "BTCUSDT", status: "completed", label: "已完成", quality: "complete" },
  { symbol: "ETHUSDT", status: "degraded", label: "已降级", quality: "analysis_unavailable" },
]) {
  test(`研究报告 ${scenario.symbol} ${scenario.status} 经后台保存后刷新和新会话可读取`, async ({ page, browser }) => {
    const backendUrl = process.env.HTTP_E2E_BACKEND_URL;
    if (backendUrl === undefined) throw new Error("HTTP E2E backend URL is missing");
    await page.goto(`/technical-reports?symbol=${scenario.symbol}`);
    await expect(page.getByRole("heading", { name: "技术分析报告", exact: true })).toBeVisible();
    await expect(page.getByText(/Mock 演示数据/)).toHaveCount(0);
    const enqueue = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.origin === backendUrl && url.pathname === "/api/v1/technical-reports/runs"
        && response.request().method() === "POST";
    });
    await page.getByRole("button", { name: "生成技术报告", exact: true }).click();
    const accepted = await enqueue;
    expect(accepted.status()).toBe(202);
    const run = await accepted.json() as { id: string; analysisId: string; status: string; symbol: string };
    expect(run.status).toBe("queued");
    expect(run.symbol).toBe(scenario.symbol);
    await expect(page).toHaveURL(/\/technical-reports\/[0-9a-f-]{36}$/);
    const reportId = new URL(page.url()).pathname.split("/").at(-1);
    if (reportId === undefined) throw new Error("Research report ID is missing");

    // APIRequestContext 直接从后端重读不可变记录，排除页面临时状态冒充保存。
    const read = await page.request.get(`${backendUrl}/api/v1/technical-reports/${reportId}`);
    expect(read.status()).toBe(200);
    const report = await read.json() as {
      id: string; analysisId: string; status: string; version: string; errorCode: string | null;
      generation: { quality: string };
    };
    expect(report.id).toBe(reportId);
    expect(report.analysisId).toBe(run.analysisId);
    expect(report.status).toBe(scenario.status);
    expect(report.version).toBe("technical-v2");
    expect(report.generation.quality).toBe(scenario.quality);
    expect(report.errorCode).toBe(scenario.status === "degraded" ? "model_not_configured" : null);
    await expect(page.getByText(`${scenario.symbol} · ${scenario.label}`, { exact: true })).toBeVisible();
    if (scenario.status === "degraded") {
      await expect(page.getByText("模型叙事不可用：尚未配置模型。", { exact: true })).toBeVisible();
    }
    await page.reload();
    await expect(page.getByText(`${scenario.symbol} · ${scenario.label}`, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "报告与数据质量" })).toBeVisible();
    await page.getByRole("link", { name: "返回历史报告" }).click();
    await expect(page.getByRole("link", { name: "查看技术报告" }).first()).toHaveAttribute(
      "href", `/technical-reports/${reportId}`,
    );

    const fresh = await browser.newContext({ baseURL: new URL(page.url()).origin });
    try {
      const cleanPage = await fresh.newPage();
      await cleanPage.goto(`/technical-reports/${reportId}`);
      await expect(cleanPage.getByText(`${scenario.symbol} · ${scenario.label}`, { exact: true })).toBeVisible();
      await expect(cleanPage.getByText(/Mock 演示数据/)).toHaveCount(0);
    } finally {
      await fresh.close();
    }
  });
}
