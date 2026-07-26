import { expect, test, type Page } from "@playwright/test";

interface PrimaryDestination {
  linkName: string;
  url: RegExp;
  heading: string;
}

const primaryDestinations: PrimaryDestination[] = [
  {
    linkName: "BTCUSDT 市场",
    url: /\/market\/BTCUSDT$/,
    heading: "BTCUSDT 市场详情",
  },
  {
    linkName: "分析报告",
    url: /\/reports$/,
    heading: "分析报告",
  },
  {
    linkName: "交易日志",
    url: /\/trades$/,
    heading: "交易日志",
  },
  {
    linkName: "复盘统计",
    url: /\/analytics$/,
    heading: "复盘统计",
  },
  {
    linkName: "设置",
    url: /\/settings$/,
    heading: "设置",
  },
];

async function expectMainAndHeading(page: Page, heading: string) {
  await expect(page.getByRole("main")).toBeVisible();
  await expect(
    page.getByRole("heading", { exact: true, name: heading }),
  ).toBeVisible();
}

test("primary routes are reachable without a mouse and retain semantic landmarks", async ({
  page,
}) => {
  await page.goto("/");
  await expectMainAndHeading(page, "研究工作台");

  for (const destination of primaryDestinations) {
    const navigationLink = page.getByRole("link", {
      exact: true,
      name: destination.linkName,
    });
    await navigationLink.focus();
    await expect(navigationLink).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(destination.url);
    await expectMainAndHeading(page, destination.heading);
  }
});
