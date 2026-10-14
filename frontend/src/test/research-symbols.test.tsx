import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "../app/providers";
import { AppRouter } from "../app/router";
import { MockWorkbenchApi } from "../shared/api/mock-workbench-api";
import { WorkbenchHttpError } from "../shared/api/http-transport";

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candlestick", ColorType: { Solid: "solid" },
  createChart: () => ({ addSeries: () => ({ setData: () => undefined }), applyOptions: () => undefined, remove: () => undefined, timeScale: () => ({ fitContent: () => undefined }) }),
}));

function show(path: string, api = new MockWorkbenchApi()) {
  window.history.replaceState({}, "", path);
  return render(<AppProviders api={api}><AppRouter /></AppProviders>);
}

beforeEach(() => { localStorage.clear(); });

describe("research directory journeys", () => {
  it("adds an offline SOL example, displays unsupported ETF, and remembers it across research pages", async () => {
    const user = userEvent.setup();
    const api = new MockWorkbenchApi();
    const view = show("/research-symbols", api);
    await user.type(await screen.findByRole("textbox", { name: "币对" }), " solusdt ");
    await user.click(screen.getByRole("button", { name: "检查并添加" }));
    const card = await screen.findByRole("article", { name: "SOLUSDT" });
    expect(within(card).getByText(/当前数据源不支持/)).toBeVisible();
    expect(screen.getByText(/离线示例/)).toBeVisible();
    view.unmount();
    const dashboard = show("/?symbol=SOLUSDT", api);
    expect(await screen.findByRole("combobox", { name: "研究币对" })).toHaveValue("SOLUSDT");
    await screen.findByRole("heading", { name: "研究工作台" });
    dashboard.unmount();
    const market = show("/market", api);
    await screen.findByRole("heading", { name: "SOLUSDT 市场详情" });
    market.unmount();
    show("/reports", api);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "研究币对" })).toHaveValue("SOLUSDT"));
    expect(await screen.findByText(/为 SOLUSDT 按需抓取/)).toBeVisible();
  });

  it("keeps invalid explicit URLs recoverable without issuing a BTC dashboard request", async () => {
    const api = new MockWorkbenchApi();
    const getDashboard = vi.spyOn(api, "getDashboard");
    show("/?symbol=INVALID", api);
    await screen.findByText(/未登记|无效/);
    expect(getDashboard).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "研究币对" }), "ETHUSDT");
    await screen.findByRole("heading", { name: "研究工作台" });
    expect(getDashboard).toHaveBeenCalledWith({ symbol: "ETHUSDT" });
  });

  it("lists distinct server-provided admission reasons when adding a symbol fails", async () => {
    const user = userEvent.setup();
    const api = new MockWorkbenchApi();
    vi.spyOn(api, "addResearchSymbol").mockRejectedValue(
      new WorkbenchHttpError(
        422,
        "research_symbol_unsupported",
        "该币对暂不满足研究数据要求。",
        {
          check: {
            symbol: "ZECUSDT",
            supported: false,
            checks: [
              {
                name: "market",
                status: "unverified",
                message: "公开合约信息响应超过系统可接受的大小上限，请稍后重试。",
              },
              {
                name: "candles",
                status: "unverified",
                message: "公开合约信息响应超过系统可接受的大小上限，请稍后重试。",
              },
            ],
            metadata: null,
          },
        },
      ),
    );
    show("/research-symbols", api);

    await user.type(await screen.findByRole("textbox", { name: "币对" }), "ZECUSDT");
    await user.click(screen.getByRole("button", { name: "检查并添加" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("该币对暂不满足研究数据要求。")).toBeVisible();
    expect(
      within(alert).getByText("公开合约信息响应超过系统可接受的大小上限，请稍后重试。"),
    ).toBeVisible();
    expect(within(alert).getAllByRole("listitem")).toHaveLength(1);
  });

  it("does not query dashboard before the authoritative catalog arrives", async () => {
    const api = new MockWorkbenchApi();
    // This boundary spy deliberately delays only the directory transport.
    const list = api.listResearchSymbols.bind(api);
    let finish!: () => void;
    vi.spyOn(api, "listResearchSymbols").mockImplementation(() => new Promise(resolve => { finish = () => { void list().then(resolve); }; }));
    const getDashboard = vi.spyOn(api, "getDashboard");
    show("/", api);
    expect(screen.getByRole("combobox", { name: "研究币对" })).toBeVisible();
    expect(getDashboard).not.toHaveBeenCalled();
    act(() => finish());
    await screen.findByRole("heading", { name: "研究工作台" });
    await waitFor(() =>
      expect(getDashboard).toHaveBeenCalledWith({ symbol: "BTCUSDT" }),
    );
  });
});
