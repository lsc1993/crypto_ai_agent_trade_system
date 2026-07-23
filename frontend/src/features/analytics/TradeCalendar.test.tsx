import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { analyticsSnapshotSchema } from "../../domain/analytics";
import { TradeCalendar } from "./TradeCalendar";

describe("TradeCalendar", () => {
  it("renders UTC calendar data and announces an accessible selected-day summary", async () => {
    const user = userEvent.setup();
    const snapshot = analyticsSnapshotSchema.parse({
      netPnl: "9.40",
      winRate: "0.625",
      profitFactor: "1.75",
      expectancy: "2.35",
      maxDrawdown: "-4.00",
      equityCurve: [],
      tradeCalendar: [
        {
          at: "2025-01-11T00:00:00Z",
          netPnl: "9.40",
          tradeCount: 1,
        },
      ],
      generatedAt: "2025-01-15T12:05:00Z",
    });

    render(<TradeCalendar points={snapshot.tradeCalendar} />);

    const table = screen.getByRole("table", {
      name: "交易日历文本数据",
    });
    expect(within(table).getByText("2025-01-11")).toBeVisible();
    expect(within(table).getByText("9.40")).toBeVisible();
    expect(within(table).getByText("1")).toBeVisible();

    const day = screen.getByRole("button", {
      name: "选择 2025-01-11 UTC",
    });
    await user.click(day);

    expect(day).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent(
      "已选择 UTC 日期：2025-01-11。净盈亏：9.40；交易笔数：1。",
    );
  });
});
