import { expect, test } from "@playwright/test";

test("从报告详情仅携带报告 ID 创建研究日志", async ({ page }) => {
  await page.goto("/reports/report-btc-001");

  await expect(
    page.getByRole("heading", { name: "BTCUSDT 离线研究样例" }),
  ).toBeVisible();
  const createJournalLink = page.getByRole("link", {
    name: "基于此分析创建交易日志",
  });
  await expect(createJournalLink).toHaveAttribute(
    "href",
    "/trades/new?linkedAnalysisReportId=report-btc-001",
  );

  await createJournalLink.click();
  await expect(page).toHaveURL((url) => {
    return (
      url.pathname === "/trades/new" &&
      url.searchParams.size === 1 &&
      url.searchParams.get("linkedAnalysisReportId") === "report-btc-001"
    );
  });
  await expect(
    page.getByRole("heading", { name: "新增交易日志" }),
  ).toBeVisible();
  await expect(page.getByLabel("关联分析报告 ID")).toHaveValue(
    "report-btc-001",
  );

  await expect(page.getByLabel("研究理由")).toHaveValue("");
  await expect(page.getByLabel("复盘记录")).toHaveValue("");
  await expect(
    page.getByText("用于界面和 API 契约验证的确定性 Mock 报告。"),
  ).toHaveCount(0);
  await expect(
    page.getByText("该段落仅演示推断与事实分离。"),
  ).toHaveCount(0);
  await expect(
    page.getByText("固定样例不反映当前市场。"),
  ).toHaveCount(0);

  await page.getByLabel("标签").fill("E2E报告关联");
  await page.getByLabel("研究理由").fill("人工填写的独立研究理由。");
  const firstLeg = page.getByRole("group", { name: "交易腿 1" });
  await firstLeg.getByLabel("交易腿 ID").fill("leg-report-linked");
  await firstLeg
    .getByLabel("执行时间（UTC）")
    .fill("2025-02-11T01:00:00Z");
  await firstLeg.getByLabel("价格").fill("68000");
  await firstLeg.getByLabel("数量").fill("0.01");
  await firstLeg.getByLabel("手续费").fill("0");

  await page.getByRole("button", { name: "保存交易日志" }).click();
  await expect(page.getByText("交易日志已保存。", { exact: true })).toBeVisible();
  await expect(page).toHaveURL((url) => {
    return (
      url.pathname === "/trades/new" &&
      url.searchParams.size === 1 &&
      url.searchParams.get("linkedAnalysisReportId") === "report-btc-001"
    );
  });

  await page.goto("/trades");
  await page.getByLabel("标签").fill("E2E报告关联");
  await page.getByRole("button", { name: "应用筛选" }).click();
  const table = page.getByRole("table", { name: "交易日志记录" });
  await expect(table.getByRole("row")).toHaveCount(2);
  await expect(table.getByRole("row").nth(1)).toContainText(
    "report-btc-001",
  );

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
