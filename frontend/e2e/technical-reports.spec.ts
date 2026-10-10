import { expect, test } from "@playwright/test";

test("technical research has its own generation and historical detail", async ({ page }) => {
  await page.goto("/reports?symbol=BTCUSDT");
  await expect(page.getByRole("heading", { name: "分析报告", exact: true })).toBeVisible();
  await page.getByRole("navigation", { name: "研究报告风格" }).getByRole("link", { name: /技术分析/ }).click();
  await expect(page).toHaveURL(/\/technical-reports\?symbol=BTCUSDT$/);
  await page.getByRole("button", { name: "生成技术报告", exact: true }).click();
  await expect(page.getByRole("link", { name: "返回历史报告" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "条件研究计划" })).toBeVisible();
  await expect(page.getByText("当前无已选定的价格计划，请查看等待条件。", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", {name: "交易计划书 · 等待确认"})).toBeVisible();
  await expect(page.getByText("Mock 演示数据：未读取真实行情，也未调用 AI 模型。", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "返回历史报告" }).click();
  await page.getByRole("link", { name: "查看技术报告", exact: true }).click();
  await expect(page.getByRole("heading", { name: "报告与数据质量" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", {name: "交易计划书 · 等待确认"})).toBeVisible();
});

test("a queued technical task survives refresh without resubmission", async ({page}) => {
  await page.goto("/technical-reports?symbol=BTCUSDT");
  const runId = "11111111-1111-4111-8111-111111111111";
  await page.evaluate((id) => {
    const run = {id, analysisId: "22222222-2222-4222-8222-222222222222", symbol:"BTCUSDT", status:"queued", phase:"queued", createdAt:"2026-10-10T00:00:00Z", updatedAt:"2026-10-10T00:00:00Z", startedAt:null, finishedAt:null, reportId:null, errorCode:null};
    localStorage.setItem("technical-research-demo-v2", JSON.stringify({reports:[], runs:[run], requests:{}}));
  }, runId);
  await page.goto(`/technical-reports?symbol=BTCUSDT&runId=${runId}`);
  await expect(page.getByText("等待开始", {exact:true})).toBeVisible();
  await expect(page.getByRole("button", {name:"生成技术报告", exact:true})).toBeDisabled();
  await page.reload();
  await expect(page.getByText("等待开始", {exact:true})).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`runId=${runId}`));
});

test("invalid technical report links show a recoverable state", async ({ page }) => {
  await page.goto("/technical-reports?symbol=invalid");
  await expect(page.getByText("URL 中的研究币对格式无效。", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "研究报告风格" })).toBeVisible();
  await page.goto("/technical-reports/not-a-uuid");
  await expect(page.getByText("技术报告 ID 无效。", { exact: true })).toBeVisible();
});
