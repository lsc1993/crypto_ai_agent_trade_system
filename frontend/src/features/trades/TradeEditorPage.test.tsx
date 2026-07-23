import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../../app/providers";
import type { Page } from "../../domain/primitives";
import {
  tradeDraftSchema,
  tradeFiltersSchema,
  tradeSchema,
  type Trade,
  type TradeDraft,
  type TradeFilters,
} from "../../domain/trade";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import {
  mockTradeDraft,
  mockTrades,
} from "../../shared/mocks/fixtures";
import { TradeEditorPage } from "./TradeEditorPage";

class RecordingTradeEditorApi extends MockWorkbenchApi {
  readonly listInputs: TradeFilters[] = [];
  readonly createInputs: TradeDraft[] = [];
  readonly updateInputs: Array<{
    tradeId: string;
    draft: TradeDraft;
  }> = [];

  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    this.listInputs.push(parsed);
    return Promise.resolve({
      items: mockTrades,
      page: parsed.page,
      pageSize: parsed.pageSize,
      total: mockTrades.length,
    });
  }

  override createTrade(draft: TradeDraft): Promise<Trade> {
    const parsed = tradeDraftSchema.parse(draft);
    this.createInputs.push(parsed);
    return Promise.resolve(this.serverTrade("trade-created", parsed));
  }

  override updateTrade(
    tradeId: string,
    draft: TradeDraft,
  ): Promise<Trade> {
    const parsed = tradeDraftSchema.parse(draft);
    this.updateInputs.push({ tradeId, draft: parsed });
    return Promise.resolve(this.serverTrade(tradeId, parsed));
  }

  private serverTrade(id: string, draft: TradeDraft): Trade {
    const openedAt =
      draft.legs[0]?.executedAt ?? "2025-01-01T00:00:00Z";
    return tradeSchema.parse({
      ...draft,
      id,
      status: "open",
      netPnl: "0",
      openedAt,
      closedAt: null,
      createdAt: "2025-02-01T00:00:00Z",
      updatedAt: "2025-02-01T00:00:00Z",
    });
  }
}

class PendingTradeLookupApi extends RecordingTradeEditorApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    this.listInputs.push(tradeFiltersSchema.parse(filters));
    return new Promise(() => undefined);
  }
}

class FailingTradeLookupApi extends RecordingTradeEditorApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    this.listInputs.push(tradeFiltersSchema.parse(filters));
    return Promise.reject(
      new Error("private edit lookup detail must stay hidden"),
    );
  }
}

class MissingTradeLookupApi extends RecordingTradeEditorApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    this.listInputs.push(parsed);
    return Promise.resolve({
      items: [],
      page: parsed.page,
      pageSize: parsed.pageSize,
      total: 0,
    });
  }
}

class RoutedTradeLookupApi extends RecordingTradeEditorApi {
  override listTrades(filters: TradeFilters): Promise<Page<Trade>> {
    const parsed = tradeFiltersSchema.parse(filters);
    this.listInputs.push(parsed);
    const firstTrade = mockTrades[0];
    if (firstTrade === undefined) {
      throw new Error("Trade fixture is missing");
    }
    const secondTrade = tradeSchema.parse({
      ...firstTrade,
      id: "trade-002",
      thesis: "第二笔交易的研究理由。",
    });
    return Promise.resolve({
      items: [firstTrade, secondTrade],
      page: parsed.page,
      pageSize: parsed.pageSize,
      total: 2,
    });
  }
}

function renderNewEditor(
  api: MockWorkbenchApi = new RecordingTradeEditorApi(),
  search = "",
) {
  window.history.replaceState({}, "", `/trades/new${search}`);
  render(
    <AppProviders api={api}>
      <Routes>
        <Route path="/trades/new" element={<TradeEditorPage />} />
      </Routes>
    </AppProviders>,
  );
}

function renderEditEditor(
  api: MockWorkbenchApi = new RecordingTradeEditorApi(),
  tradeId = "trade-001",
) {
  window.history.replaceState({}, "", `/trades/${tradeId}/edit`);
  return render(
    <AppProviders api={api}>
      <Routes>
        <Route
          path="/trades/:tradeId/edit"
          element={<TradeEditorPage />}
        />
      </Routes>
    </AppProviders>,
  );
}

function fillNewDraft() {
  const user = userEvent.setup();
  const firstLeg = screen.getByRole("group", { name: "交易腿 1" });
  fireEvent.change(within(firstLeg).getByLabelText("交易腿 ID"), {
    target: { value: "leg-new-001" },
  });
  fireEvent.change(within(firstLeg).getByLabelText("执行时间（UTC）"), {
    target: { value: "2025-02-01T00:00:00Z" },
  });
  fireEvent.change(within(firstLeg).getByLabelText("价格"), {
    target: { value: "68000" },
  });
  fireEvent.change(within(firstLeg).getByLabelText("数量"), {
    target: { value: "0.01" },
  });
  fireEvent.change(within(firstLeg).getByLabelText("手续费"), {
    target: { value: "0.25" },
  });
  fireEvent.change(screen.getByLabelText("杠杆"), {
    target: { value: "2" },
  });
  fireEvent.change(screen.getByLabelText("资金费"), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText("标签"), {
    target: { value: "计划内" },
  });
  fireEvent.change(screen.getByLabelText("研究理由"), {
    target: { value: "仅用于研究记录。" },
  });
  return user;
}

describe("TradeEditorPage new journal", () => {
  it("strictly maps only linkedAnalysisReportId to linkedReportId", async () => {
    const api = new RecordingTradeEditorApi();
    renderNewEditor(
      api,
      "?linkedAnalysisReportId=report-btc-001" +
        "&summary=MUST_NOT_COPY&facts=MUST_NOT_COPY" +
        "&evidence=MUST_NOT_COPY&recommendation=MUST_NOT_COPY" +
        "&apiKey=MUST_NOT_COPY",
    );

    expect(
      await screen.findByRole("heading", { name: "新增交易日志" }),
    ).toBeVisible();
    expect(screen.getByLabelText("关联分析报告 ID")).toHaveValue(
      "report-btc-001",
    );
    expect(screen.queryByText("MUST_NOT_COPY")).not.toBeInTheDocument();

    const user = fillNewDraft();
    await user.click(
      screen.getByRole("button", { name: "保存交易日志" }),
    );

    await waitFor(() => {
      expect(api.createInputs).toHaveLength(1);
    });
    expect(api.createInputs[0]).toEqual(
      tradeDraftSchema.parse({
        ...mockTradeDraft,
        legs: [
          {
            id: "leg-new-001",
            action: "open",
            executedAt: "2025-02-01T00:00:00Z",
            price: "68000",
            quantity: "0.01",
            fee: "0.25",
          },
        ],
        thesis: "仅用于研究记录。",
        review: "",
      }),
    );
    expect(api.createInputs[0]).not.toHaveProperty("summary");
    expect(api.createInputs[0]).not.toHaveProperty("evidence");
    expect(api.createInputs[0]).not.toHaveProperty("recommendation");
    expect(api.createInputs[0]).not.toHaveProperty("apiKey");
  });

  it("rejects duplicate or invalid linked report query values", async () => {
    renderNewEditor(
      new RecordingTradeEditorApi(),
      "?linkedAnalysisReportId=report-one" +
        "&linkedAnalysisReportId=report-two&unknown=MUST_NOT_COPY",
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "关联分析报告参数无效，已安全忽略。",
    );
    expect(screen.getByLabelText("关联分析报告 ID")).toHaveValue("");
    expect(screen.queryByText("MUST_NOT_COPY")).not.toBeInTheDocument();
  });

  it("blocks accounting-invalid legs before createTrade", async () => {
    const api = new RecordingTradeEditorApi();
    renderNewEditor(api);
    const user = fillNewDraft();
    await user.click(
      screen.getByRole("button", { name: "添加交易腿" }),
    );
    const secondLeg = screen.getByRole("group", { name: "交易腿 2" });
    await user.selectOptions(
      within(secondLeg).getByLabelText("动作"),
      "close",
    );
    fireEvent.change(within(secondLeg).getByLabelText("执行时间（UTC）"), {
      target: { value: "2025-02-01T01:00:00Z" },
    });
    fireEvent.change(within(secondLeg).getByLabelText("价格"), {
      target: { value: "68100" },
    });
    fireEvent.change(within(secondLeg).getByLabelText("数量"), {
      target: { value: "0.02" },
    });
    fireEvent.change(within(secondLeg).getByLabelText("手续费"), {
      target: { value: "0" },
    });
    await user.click(
      screen.getByRole("button", { name: "保存交易日志" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "减仓或平仓数量不能超过累计开仓数量。",
    );
    expect(api.createInputs).toEqual([]);
  });
});

describe("TradeEditorPage edit journal", () => {
  it("loads an edit record through listTrades page 1 pageSize 100", async () => {
    const api = new RecordingTradeEditorApi();
    renderEditEditor(api);

    expect(
      await screen.findByRole("heading", { name: "编辑交易日志" }),
    ).toBeVisible();
    expect(api.listInputs).toEqual([{ page: 1, pageSize: 100 }]);
    expect(screen.getByLabelText("研究理由")).toHaveValue(
      "固定 Mock 入场依据。",
    );
  });

  it("updates the routed record with a parsed TradeDraft", async () => {
    const user = userEvent.setup();
    const api = new RecordingTradeEditorApi();
    renderEditEditor(api);
    await screen.findByRole("heading", { name: "编辑交易日志" });

    await user.clear(screen.getByLabelText("复盘记录"));
    await user.type(screen.getByLabelText("复盘记录"), "更新后的复盘。");
    await user.click(
      screen.getByRole("button", { name: "保存交易日志" }),
    );

    await waitFor(() => {
      expect(api.updateInputs).toHaveLength(1);
    });
    expect(api.updateInputs[0]?.tradeId).toBe("trade-001");
    expect(api.updateInputs[0]?.draft.review).toBe("更新后的复盘。");
  });

  it("uses the routed trade ID in lookup caching and resets the form in place", async () => {
    const user = userEvent.setup();
    const api = new RoutedTradeLookupApi();
    window.history.replaceState({}, "", "/trades/trade-001/edit");
    render(
      <AppProviders api={api}>
        <Link to="/trades/trade-002/edit">切换交易日志</Link>
        <Routes>
          <Route
            path="/trades/:tradeId/edit"
            element={<TradeEditorPage />}
          />
        </Routes>
      </AppProviders>,
    );

    expect(await screen.findByLabelText("研究理由")).toHaveValue(
      "固定 Mock 入场依据。",
    );
    await user.click(
      screen.getByRole("link", { name: "切换交易日志" }),
    );

    await waitFor(() => {
      expect(screen.getByLabelText("研究理由")).toHaveValue(
        "第二笔交易的研究理由。",
      );
    });
    expect(api.listInputs).toEqual([
      { page: 1, pageSize: 100 },
      { page: 1, pageSize: 100 },
    ]);
  });

  it("renders safe loading, error, and missing states for edit lookup", async () => {
    const pending = new PendingTradeLookupApi();
    const pendingView = renderEditEditor(pending);
    expect(screen.getByText("正在加载数据")).toBeVisible();
    expect(pending.listInputs).toEqual([{ page: 1, pageSize: 100 }]);
    pendingView.unmount();

    renderEditEditor(new FailingTradeLookupApi());
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("无法读取待编辑的交易日志。");
    expect(error).not.toHaveTextContent("private edit lookup detail");

    renderEditEditor(new MissingTradeLookupApi());
    expect(await screen.findByText("未找到指定的交易日志。")).toBeVisible();
  });
});
