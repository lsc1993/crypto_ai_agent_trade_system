import { expect, test } from "@playwright/test";

test("analytics exposes accessible Mock review data, text alternatives, and calendar selection", async ({
  page,
}, testInfo) => {
  await page.goto("/analytics");

  await expect(page.getByRole("main")).toBeVisible();
  await expect(
    page.getByRole("heading", { exact: true, name: "复盘统计" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "核心复盘指标" })
      .getByText("净盈亏", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /权益曲线，共 \d+ 个数据点/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "权益曲线文本数据" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "交易日历文本数据" }),
  ).toBeVisible();

  const calendarDay = page.getByRole("button", {
    name: "选择 2025-01-11 UTC",
  });
  await calendarDay.focus();
  await expect(calendarDay).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(calendarDay).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("status").filter({ hasText: "已选择 UTC 日期" }),
  ).toContainText("已选择 UTC 日期：2025-01-11。净盈亏：9.40；交易笔数：1。");

  await page.screenshot({
    path: testInfo.outputPath("analytics-populated.png"),
    fullPage: false,
  });

  await page.getByLabel("标的").selectOption("ETHUSDT");
  const applyFilters = page.getByRole("button", {
    exact: true,
    name: "应用筛选条件",
  });
  await applyFilters.focus();
  await page.keyboard.press("Enter");

  await expect(
    page.getByText("当前筛选条件下暂无可复盘的交易统计。"),
  ).toBeVisible();
});
