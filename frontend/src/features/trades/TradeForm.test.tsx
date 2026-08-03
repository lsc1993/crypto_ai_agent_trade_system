import {
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  tradeDraftSchema,
  type TradeDraft,
} from "../../domain/trade";
import { mockTradeDraft } from "../../shared/mocks/fixtures";
import { TradeForm } from "./TradeForm";
import { parseTradeFormDraft } from "./trade-form-schema";

function validDraft(): TradeDraft {
  return tradeDraftSchema.parse(mockTradeDraft);
}

describe("parseTradeFormDraft", () => {
  it.each([
    ["zero price", { price: "0" }],
    ["negative quantity", { quantity: "-1" }],
    ["exponent quantity", { quantity: "1e-3" }],
    ["non-UTC time", { executedAt: "2025-01-16T09:00:00+08:00" }],
    ["invalid calendar time", { executedAt: "2025-02-30T00:00:00Z" }],
  ])("rejects %s at the untrusted form boundary", (_, legPatch) => {
    const draft = validDraft();
    expect(() =>
      parseTradeFormDraft({
        ...draft,
        legs: [{ ...draft.legs[0], ...legPatch }],
      }),
    ).toThrow();
  });

  it("rejects duplicate leg IDs", () => {
    const draft = validDraft();
    const open = draft.legs[0];
    if (open === undefined) {
      throw new Error("Open leg fixture is missing");
    }
    expect(() =>
      parseTradeFormDraft({
        ...draft,
        legs: [
          open,
          {
            ...open,
            action: "reduce",
            quantity: "0.001",
          },
        ],
      }),
    ).toThrow(/unique/i);
  });

  it("rejects non-UTC cashflows and accepts signed cashflow amounts", () => {
    const draft = validDraft();
    expect(() =>
      parseTradeFormDraft({
        ...draft,
        fundingCashflows: [
          {
            id: "cashflow-invalid-time",
            occurredAt: "2025-01-16T09:00:00+08:00",
            amount: "0.10",
            reason: "funding received",
          },
        ],
      }),
    ).toThrow();
    expect(
      parseTradeFormDraft({
        ...draft,
        fundingCashflows: [
          {
            id: "cashflow-positive",
            occurredAt: "2025-01-16T01:00:00Z",
            amount: "0.10",
            reason: "funding received",
          },
        ],
      }).fundingCashflows[0]?.amount,
    ).toBe("0.10");
  });

  it.each([
    [
      "reduction above opened quantity",
      { action: "reduce", quantity: "2" },
      /exceed/i,
    ],
    [
      "close above opened quantity",
      { action: "close", quantity: "2" },
      /exceed/i,
    ],
    [
      "reduce that clears the position",
      { action: "reduce", quantity: "1" },
      /leave quantity open/i,
    ],
    [
      "close that leaves quantity open",
      { action: "close", quantity: "0.5" },
      /exactly clear/i,
    ],
  ])("rejects %s", (_, closingLeg, message) => {
    const draft = validDraft();
    expect(() =>
      parseTradeFormDraft({
        ...draft,
        legs: [
          {
            id: "leg-open",
            action: "open",
            executedAt: "2025-01-16T00:00:00Z",
            price: "100",
            quantity: "1",
            fee: "0",
          },
          {
            id: "leg-reduction",
            executedAt: "2025-01-16T01:00:00Z",
            price: "101",
            fee: "0",
            ...closingLeg,
          },
        ],
      }),
    ).toThrow(message);
  });

  it("rejects unexpected top-level fields instead of admitting them to a draft", () => {
    expect(() =>
      parseTradeFormDraft({
        ...validDraft(),
        reportBody: "MUST_NOT_ENTER_DRAFT",
        apiKey: "MUST_NOT_ENTER_DRAFT",
      }),
    ).toThrow();
  });
});

describe("TradeForm", () => {
  it("adds and removes uniquely identified trade legs", async () => {
    const user = userEvent.setup();
    render(
      <TradeForm
        initialDraft={validDraft()}
        submitLabel="保存交易日志"
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("group", { name: /交易腿/ })).toHaveLength(
      1,
    );
    await user.click(
      screen.getByRole("button", { name: "添加交易腿" }),
    );

    const groups = screen.getAllByRole("group", { name: /交易腿/ });
    expect(groups).toHaveLength(2);
    const firstId = within(groups[0] ?? document.body).getByLabelText(
      "交易腿 ID",
    );
    const secondId = within(groups[1] ?? document.body).getByLabelText(
      "交易腿 ID",
    );
    expect(firstId).not.toHaveValue(secondId.getAttribute("value"));

    await user.click(
      within(groups[1] ?? document.body).getByRole("button", {
        name: "移除交易腿 2",
      }),
    );
    expect(screen.getAllByRole("group", { name: /交易腿/ })).toHaveLength(
      1,
    );
  });

  it("keeps exact DecimalString inputs while decimal.js is display-only", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(draft: TradeDraft) => void>();
    const draft = validDraft();
    const preciseDraft = tradeDraftSchema.parse({
      ...draft,
      legs: [
        {
          ...draft.legs[0],
          price: "123456789012345678.12",
          quantity: "0.000000000000000001",
        },
      ],
    });
    render(
      <TradeForm
        initialDraft={preciseDraft}
        submitLabel="保存交易日志"
        onSubmit={onSubmit}
      />,
    );

    expect(
      screen.getByText(
        "名义价值预览：0.12345678901234567812 USDT",
      ),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "保存交易日志" }),
    );

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submitted = onSubmit.mock.calls[0]?.[0];
    expect(submitted?.legs[0]?.price).toBe("123456789012345678.12");
    expect(submitted?.legs[0]?.quantity).toBe(
      "0.000000000000000001",
    );
  });

  it("submits a signed UTC cashflow row with its explanation", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(draft: TradeDraft) => void>();
    render(
      <TradeForm
        initialDraft={validDraft()}
        submitLabel="保存交易日志"
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: "添加资金现金流" }));
    const group = screen.getByRole("group", { name: "资金现金流 1" });
    await user.clear(within(group).getByLabelText("发生时间（UTC）"));
    await user.type(
      within(group).getByLabelText("发生时间（UTC）"),
      "2026-07-31T01:00:00Z",
    );
    await user.clear(within(group).getByLabelText("资金现金流"));
    await user.type(within(group).getByLabelText("资金现金流"), "-0.25");
    await user.clear(within(group).getByLabelText("说明"));
    await user.type(within(group).getByLabelText("说明"), "funding payment");
    await user.click(screen.getByRole("button", { name: "保存交易日志" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        fundingCashflows: [
          expect.objectContaining({
            occurredAt: "2026-07-31T01:00:00Z",
            amount: "-0.25",
            reason: "funding payment",
          }),
        ],
      }),
    );
  });

  it("uses Chinese accessible journal copy without execution controls", () => {
    render(
      <TradeForm
        initialDraft={validDraft()}
        submitLabel="保存交易日志"
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("标的")).toBeVisible();
    expect(screen.getByLabelText("方向")).toBeVisible();
    expect(screen.getByLabelText("持有周期")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "添加资金现金流" }),
    ).toBeVisible();
    expect(screen.getByLabelText("研究理由")).toBeVisible();
    expect(screen.getByLabelText("复盘记录")).toBeVisible();
    expect(
      screen.getByText(
        "客户端校验仅用于即时提示；后端服务仍是最终权威。",
      ),
    ).toBeVisible();
    for (const control of screen.getAllByRole("button")) {
      expect(control).not.toHaveAccessibleName(
        /下单|开仓|自动交易|执行交易/,
      );
    }
  });
});
