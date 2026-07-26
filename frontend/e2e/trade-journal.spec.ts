import { expect, test } from "@playwright/test";

test("新建多腿 Mock 交易日志并按标签筛选", async ({ page }) => {
  await page.goto("/trades/new");

  await expect(
    page.getByRole("heading", { name: "新增交易日志" }),
  ).toBeVisible();
  await expect(
    page.getByText("仅记录人工研究过程与复盘，不连接账户，也不触发任何交易执行。"),
  ).toBeVisible();

  await page.getByLabel("标签").fill("E2E多腿复盘");
  await page.getByLabel("研究理由").fill("仅用于验证多腿模拟日志流程。");

  const firstLeg = page.getByRole("group", { name: "交易腿 1" });
  await firstLeg.getByLabel("交易腿 ID").fill("leg-e2e-open");
  await firstLeg
    .getByLabel("执行时间（UTC）")
    .fill("2025-02-10T01:00:00Z");
  await firstLeg.getByLabel("价格").fill("68000.10");
  await firstLeg.getByLabel("数量").fill("0.010");
  await firstLeg.getByLabel("手续费").fill("0.25");

  await page.getByRole("button", { name: "添加交易腿" }).click();
  const reduceLeg = page.getByRole("group", { name: "交易腿 2" });
  await reduceLeg.getByLabel("交易腿 ID").fill("leg-e2e-reduce");
  await reduceLeg.getByLabel("动作").selectOption("reduce");
  await reduceLeg
    .getByLabel("执行时间（UTC）")
    .fill("2025-02-10T02:00:00Z");
  await reduceLeg.getByLabel("价格").fill("68100.20");
  await reduceLeg.getByLabel("数量").fill("0.004");
  await reduceLeg.getByLabel("手续费").fill("0.10");

  await page.getByRole("button", { name: "添加交易腿" }).click();
  const closeLeg = page.getByRole("group", { name: "交易腿 3" });
  await closeLeg.getByLabel("交易腿 ID").fill("leg-e2e-close");
  await closeLeg.getByLabel("动作").selectOption("close");
  await closeLeg
    .getByLabel("执行时间（UTC）")
    .fill("2025-02-10T03:00:00Z");
  await closeLeg.getByLabel("价格").fill("68200.30");
  await closeLeg.getByLabel("数量").fill("0.006");
  await closeLeg.getByLabel("手续费").fill("0.15");

  await page.getByRole("button", { name: "保存交易日志" }).click();
  await expect(page.getByText("交易日志已保存。", { exact: true })).toBeVisible();

  await page.goto("/trades");
  await page.getByLabel("标签").fill("E2E多腿复盘");
  await page.getByRole("button", { name: "应用筛选" }).click();

  const table = page.getByRole("table", { name: "交易日志记录" });
  await expect(table.getByRole("row")).toHaveCount(2);
  const result = table.getByRole("row").nth(1);
  await expect(result).toContainText("BTCUSDT");
  await expect(result).toContainText("已结束");
  await expect(result).toContainText("3");

  await expect(
    page.getByRole("button", {
      name: /真实下单|提交订单|自动交易|执行交易/,
    }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", {
      name: /真实下单|提交订单|自动交易|执行交易/,
    }),
  ).toHaveCount(0);
});
