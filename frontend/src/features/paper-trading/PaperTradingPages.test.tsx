import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../../app/App";
import {
  paperAccountDetailSchema,
  type PaperAccountCreate,
  type PaperAccountDetail,
  type PaperAccountSummary,
} from "../../domain/paper-trading";
import type { Page } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";

const accountId = "00000000-0000-4000-8000-000000000801";

function createAccount(
  initialCash = "10000",
  overrides: Partial<PaperAccountDetail> = {},
): PaperAccountDetail {
  return paperAccountDetailSchema.parse({
    id: accountId,
    status: "active",
    symbol: "BTCUSDT",
    initialCash,
    cash: initialCash,
    equity: initialCash,
    peakEquity: initialCash,
    dailyStartEquity: initialCash,
    dailyRealizedLoss: "0",
    dailyDay: "2026-08-04",
    cooldownRemaining: 0,
    lastClosedCandleAt: null,
    riskConfig: {
      maxExposureFraction: "0.2",
      stopLossFraction: "0.02",
      dailyLossFraction: "0.03",
      maxDrawdownFraction: "0.15",
      cooldownCandles: 3,
      quantityIncrement: "0.0001",
    },
    executionConfig: {
      feeRate: "0.001",
      slippageRate: "0.0005",
      fillRatio: "1",
    },
    createdAt: "2026-08-04T00:00:00Z",
    archivedAt: null,
    position: {
      quantity: "0",
      averageEntryPrice: null,
      remainingEntryCost: "0",
      openedAt: null,
      updatedAt: "2026-08-04T00:00:00Z",
    },
    latestSnapshot: null,
    orders: [],
    fills: [],
    ledgerEntries: [],
    events: [],
    actionOutcome: null,
    ...overrides,
  });
}

class PaperAccountsApi extends MockWorkbenchApi {
  readonly createRequests: PaperAccountCreate[] = [];

  account = createAccount();

  override listPaperAccounts(): Promise<Page<PaperAccountSummary>> {
    return Promise.resolve({ items: [], page: 1, pageSize: 20, total: 0 });
  }

  override createPaperAccount(
    input: PaperAccountCreate,
  ): Promise<PaperAccountDetail> {
    this.createRequests.push(input);
    this.account = createAccount(input.initialCash);
    return Promise.resolve(this.account);
  }

  override getPaperAccount(accountIdToRead: string): Promise<PaperAccountDetail> {
    return Promise.resolve({ ...this.account, id: accountIdToRead });
  }
}

function renderPaperTrading(api: PaperAccountsApi = new PaperAccountsApi()) {
  window.history.replaceState({}, "", "/paper-trading");
  render(<App api={api} dataMode="mock" />);
  return api;
}

function renderPaperAccountDetail(api: PaperAccountsApi) {
  window.history.replaceState({}, "", `/paper-trading/${accountId}`);
  render(<App api={api} dataMode="mock" />);
}

class PendingStrategyPaperAccountsApi extends PaperAccountsApi {
  resolveEvaluation: ((account: PaperAccountDetail) => void) | null = null;

  override evaluatePaperStrategy(): Promise<PaperAccountDetail> {
    return new Promise((resolve) => {
      this.resolveEvaluation = resolve;
    });
  }
}

class ArchivablePaperAccountsApi extends PaperAccountsApi {
  override archivePaperAccount(): Promise<PaperAccountDetail> {
    this.account = createAccount(this.account.initialCash, {
      status: "archived",
      archivedAt: "2026-08-04T00:10:00Z",
    });
    return Promise.resolve(this.account);
  }
}

describe("paper trading pages", () => {
  it("creates a paper account and navigates to its auditable detail", async () => {
    const user = userEvent.setup();
    const api = renderPaperTrading();

    expect(
      await screen.findByRole("heading", { name: "模拟盘" }),
    ).toBeVisible();
    const createButton = await screen.findByRole("button", {
      name: "创建模拟盘",
    });
    expect(
      screen.getByText("仅模拟，不连接真实账户或产生真实订单。"),
    ).toBeVisible();

    const initialCash = screen.getByLabelText("初始资金（USDT）");
    await user.clear(initialCash);
    await user.type(initialCash, "12000");
    await user.click(createButton);

    expect(api.createRequests).toEqual([{ initialCash: "12000" }]);
    expect(window.location.pathname).toBe(`/paper-trading/${accountId}`);
    expect(
      await screen.findByRole("heading", { name: "模拟盘详情" }),
    ).toBeVisible();
  });

  it("disables only the strategy evaluation that is currently in flight", async () => {
    const user = userEvent.setup();
    const api = new PendingStrategyPaperAccountsApi();
    renderPaperAccountDetail(api);

    const evaluate = await screen.findByRole("button", {
      name: "运行 SMA 策略评估",
    });
    const openLong = screen.getByRole("button", { name: "手动开多" });

    await user.click(evaluate);

    expect(evaluate).toBeDisabled();
    expect(openLong).toBeEnabled();

    api.resolveEvaluation?.(api.account);
    expect(await screen.findByRole("button", { name: "运行 SMA 策略评估" })).toBeEnabled();
  });

  it("renders a no-signal strategy result together with its immutable audit event", async () => {
    const api = new PaperAccountsApi();
    api.account = createAccount("10000", {
      actionOutcome: {
        kind: "no_signal",
        source: "strategy",
        idempotencyKey: null,
        reason: "SMA 20 / 50 没有新的交叉信号。",
      },
      events: [
        {
          sequence: 1,
          kind: "no_signal",
          occurredAt: "2026-08-04T00:00:00Z",
          idempotencyKey: null,
          payload: { reason: "SMA 20 / 50 没有新的交叉信号。" },
        },
      ],
    });
    renderPaperAccountDetail(api);

    expect(
      await screen.findByText(
        (_, element) =>
          element?.tagName === "P" &&
          element.textContent?.includes("SMA 20 / 50 没有新的交叉信号。") ===
            true,
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "模拟盘审计事件" }),
    ).toHaveTextContent("无信号");
  });

  it("shows the local API and database requirement in Mock mode", async () => {
    window.history.replaceState({}, "", "/paper-trading");
    render(<App api={new MockWorkbenchApi()} dataMode="mock" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "模拟盘需要本地 API 与数据库",
    );
  });

  it("does not archive an active flat account when browser confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const api = new ArchivablePaperAccountsApi();
    vi.stubGlobal("confirm", () => false);
    renderPaperAccountDetail(api);

    await user.click(
      await screen.findByRole("button", { name: "归档模拟盘" }),
    );

    expect(screen.getByRole("button", { name: "归档模拟盘" })).toBeVisible();
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});
