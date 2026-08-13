# 市场页底部折叠 K 线文本数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将 BTCUSDT 等市场页中当前周期的 OHLC 文本表移动至市场资讯之后，并以默认关闭、可键盘操作的折叠区提供。

**Architecture:** 保持 `MarketChart` 仅负责交互式 K 线图与空态，抽出只渲染格式化 OHLC 表格的 `MarketCandleDataTable`。`MarketPage` 在 `NewsTimeline` 后通过无受控 React 状态的原生 `<details>` 组合这两个单一职责组件，周期切换继续由现有 `selectedSeries` 驱动。

**Tech Stack:** React 19、TypeScript、Vitest、React Testing Library、原生 HTML `<details>` / `<summary>`、现有 CSS。

## Global Constraints

- 不新增前端依赖，也不更改 `lightweight-charts`、行情 API、领域模型或公开市场研究边界。
- 继续使用加密货币惯例的涨绿（`#22c55e`）、跌红（`#ef4444`）K 线图；本次只调整文本 OHLC 表的页面布局。
- 折叠区不添加 `open` 属性，默认关闭；无 K 线数据时不得渲染空折叠区。
- 表格保留完整 OHLC、成交量、开盘/收盘时间、格式化输出与 `<caption>` 语义。
- 折叠区必须位于 `NewsTimeline` 之后，成为市场页最后一个内容区；摘要与表格必须随当前周期同步。
- 使用测试先行；不修改 `.env`、行情源、交易、下单或账户相关代码。

---

## File Structure

- Create: `frontend/src/features/market/MarketCandleDataTable.tsx` — 从图表组件分离、只渲染一个 `CandleSeries` 的完整文本表格。
- Modify: `frontend/src/features/market/MarketChart.tsx` — 移除表格与格式化依赖，使其只输出图表、图注和空态。
- Modify: `frontend/src/features/market/MarketPage.tsx` — 在资讯之后放置默认关闭的原生折叠区，并将当前 `selectedSeries` 传给表格组件。
- Modify: `frontend/src/features/market/MarketPage.test.tsx` — 覆盖默认关闭、点击展开、周期同步和无数据隐藏。
- Modify: `frontend/src/styles/index.css` — 为折叠容器和摘要增加与现有深色研究面板一致的视觉与焦点样式；复用已有表格横向滚动样式。

## Task 1: 抽离文本 OHLC 表格

**Files:**
- Create: `frontend/src/features/market/MarketCandleDataTable.tsx`
- Modify: `frontend/src/features/market/MarketChart.tsx:8-11, 114-157`
- Test: `frontend/src/features/market/MarketPage.test.tsx:392-410` (existing regression coverage)

**Interfaces:**
- Consumes: `CandleSeries` from `frontend/src/domain/market.ts`, `formatMarketPrice` and `formatMarketVolume` from `frontend/src/shared/format.ts`.
- Produces: `MarketCandleDataTable({ series }: { series: CandleSeries }): JSX.Element`, containing `<table className="market-table">` with caption `${series.timeframe} K 线文本数据`.

- [x] **Step 1: Establish the existing rendered-table regression baseline**

The existing `renders formatted derivative metrics with explicit freshness metadata` test already asserts the user-visible `1h K 线文本数据` table. Run it before refactoring; its failure would catch a missing table, caption, or inaccessible table name after extraction.

Run: `npm run test -- --run frontend/src/features/market/MarketPage.test.tsx`

Expected: PASS. This is a behavior-preserving refactor; the new default-collapsed behavior is introduced with a new red-green test in Task 2.

- [x] **Step 2: Create the table-only component**

Create `MarketCandleDataTable.tsx` with the existing table markup moved verbatim from `MarketChart`, retaining the row key and formatting behavior:

```tsx
import type { CandleSeries } from "../../domain/market";
import {
  formatMarketPrice,
  formatMarketVolume,
} from "../../shared/format";

export function MarketCandleDataTable({
  series,
}: {
  series: CandleSeries;
}) {
  return (
    <div className="table-scroll">
      <table className="market-table">
        <caption>{series.timeframe} K 线文本数据</caption>
        <thead>
          <tr>
            <th scope="col">开盘时间</th>
            <th scope="col">开盘</th>
            <th scope="col">最高</th>
            <th scope="col">最低</th>
            <th scope="col">收盘</th>
            <th scope="col">成交量</th>
            <th scope="col">收盘时间</th>
          </tr>
        </thead>
        <tbody>
          {series.candles.map((candle) => (
            <tr key={`${candle.timeframe}-${candle.openTime}`}>
              <td><time dateTime={candle.openTime}>{candle.openTime}</time></td>
              <td>{formatMarketPrice(candle.open)}</td>
              <td>{formatMarketPrice(candle.high)}</td>
              <td>{formatMarketPrice(candle.low)}</td>
              <td>{formatMarketPrice(candle.close)}</td>
              <td>{formatMarketVolume(candle.volume)}</td>
              <td><time dateTime={candle.closeTime}>{candle.closeTime}</time></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

Remove `formatMarketPrice` and `formatMarketVolume` imports plus the `<div className="table-scroll">…</div>` block from `MarketChart`; leave its chart creation, ARIA label, figure caption and empty state unchanged.

- [x] **Step 3: Run the targeted test to verify the refactor preserves behavior**

Run: `npm run test -- --run frontend/src/features/market/MarketPage.test.tsx`

Expected: PASS. The existing page test demonstrates that the table remains accessible with the unchanged caption and values after extraction, while `MarketChart` no longer owns the table markup.

- [x] **Step 4: Commit the isolated extraction when working on a clean branch**

```bash
git add frontend/src/features/market/MarketCandleDataTable.tsx frontend/src/features/market/MarketChart.tsx
git commit -m "refactor: extract market candle data table"
```

## Task 2: 在页面底部实现默认关闭的文本数据区

**Files:**
- Modify: `frontend/src/features/market/MarketPage.tsx:15, 170-178`
- Modify: `frontend/src/features/market/MarketPage.test.tsx:392-410`
- Modify: `frontend/src/styles/index.css:571-601`

**Interfaces:**
- Consumes: `selectedSeries: CandleSeries | undefined` computed by `MarketPage`, and `MarketCandleDataTable` from Task 1.
- Produces: a `<details className="market-candle-data" aria-label={`${selectedSeries.timeframe} K 线文本数据`}>` after `NewsTimeline`; its summary text is `查看 ${selectedSeries.timeframe} K 线文本数据`.

- [x] **Step 1: Extend the failing test for opening and period synchronization**

Add the following test to `MarketPage.test.tsx`:

```tsx
it("keeps OHLC text data collapsed by default and synchronizes it with the selected timeframe", async () => {
  const user = userEvent.setup();
  renderMarket();

  const summary = await screen.findByText("查看 1h K 线文本数据");
  const details = summary.closest("details");
  if (details === null) {
    throw new Error("K 线文本数据必须使用原生 details 折叠区");
  }
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByRole("table", { name: "1h K 线文本数据" })).toBeInTheDocument();
  const newsPanel = screen.getByRole("region", { name: "市场资讯" });
  expect(
    newsPanel.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).not.toBe(0);

  await user.click(summary);
  expect(details).toHaveAttribute("open");

  await user.click(screen.getByRole("tab", { name: "4h" }));
  expect(await screen.findByText("查看 4h K 线文本数据")).toBeVisible();
  expect(screen.getByRole("table", { name: "4h K 线文本数据" })).toBeInTheDocument();
});
```

In `renders formatted derivative metrics with explicit freshness metadata`, replace the old visible-table assertion with the following assertion because the final table is intentionally inside a closed `<details>` element:

```tsx
expect(
  screen.getByRole("table", { name: "1h K 线文本数据" }),
).toBeInTheDocument();
```

In the existing `EmptySectionsMarketApi` test, add:

```tsx
expect(screen.queryByText(/查看 .* K 线文本数据/)).not.toBeInTheDocument();
```

- [x] **Step 2: Run the targeted test and verify it fails**

Run: `npm run test -- --run frontend/src/features/market/MarketPage.test.tsx`

Expected: FAIL because `MarketPage` does not yet render the summary or forward `selectedSeries` to the extracted component.

- [x] **Step 3: Render native disclosure after news and add its styles**

Import `MarketCandleDataTable` and add this exact conditional immediately after `<NewsTimeline />` in `MarketPage`:

```tsx
{selectedSeries !== undefined && selectedSeries.candles.length > 0 ? (
  <details
    className="market-candle-data"
    aria-label={`${selectedSeries.timeframe} K 线文本数据`}
  >
    <summary>查看 {selectedSeries.timeframe} K 线文本数据</summary>
    <MarketCandleDataTable series={selectedSeries} />
  </details>
) : null}
```

Add the following stylesheet rules directly before `.table-scroll`:

```css
.market-candle-data {
  padding: 1.2rem;
  border: 1px solid var(--border);
  border-radius: 0.95rem;
  background: var(--surface);
}

.market-candle-data > summary {
  cursor: pointer;
  color: var(--text);
  font-weight: 750;
}

.market-candle-data > summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 0.3rem;
}

.market-candle-data[open] > summary {
  margin-bottom: 1rem;
}
```

Do not set `open`, add React disclosure state, or alter the existing `.market-table` and `.table-scroll` semantics.

- [x] **Step 4: Run focused tests and validate static checks**

Run:

```bash
npm run test -- --run frontend/src/features/market/MarketPage.test.tsx frontend/src/features/market/MarketChart.component.test.tsx frontend/src/features/market/MarketChart.test.ts
npm run lint
npm run typecheck
```

Expected: all commands exit 0. The existing chart component test verifies the chart lifecycle still works; the page test verifies default closure, user expansion, selected-period labels and absence of an empty disclosure.

- [x] **Step 5: Commit the composed layout when working on a clean branch**

```bash
git add frontend/src/features/market/MarketPage.tsx frontend/src/features/market/MarketPage.test.tsx frontend/src/styles/index.css
git commit -m "feat: collapse market candle text data"
```

## Task 3: 全量回归与 Docker Compose 验收

**Files:**
- Modify: none unless Task 1 or Task 2 verification exposes a concrete defect.
- Test: frontend test suite and running Compose frontend at `http://localhost:8080/market/BTCUSDT`.

**Interfaces:**
- Consumes: completed chart-only `MarketChart`, page-level `<details>` disclosure, and existing API-mode Compose configuration.
- Produces: verified production frontend serving a default-collapsed K 线文本数据 section without changing API behavior.

- [x] **Step 1: Run the complete frontend verification suite**

Run:

```bash
npm run test -- --run
npm run build
```

Expected: tests and production build exit 0. Record any pre-existing Vite chunk-size warning as a warning only, not a failure.

- [x] **Step 2: Rebuild the user-run Compose stack**

Run: `docker compose up -d --build`

Expected: all declared services finish building or reuse valid layers and are running. Do not modify `.env`, credentials, API mode, or container data.

- [x] **Step 3: Perform browser acceptance checks on BTCUSDT**

Open `http://localhost:8080/market/BTCUSDT` and verify:

```text
1. The selected 1h chart shows the existing green-up/red-down candlesticks.
2. "查看 1h K 线文本数据" appears after the market news section.
3. The page first loads without the details `open` attribute.
4. Activating the summary reveals the complete OHLC table with its 1h caption.
5. Selecting 4h changes both the summary and table caption to 4h.
```

- [x] **Step 4: Commit the verified documentation only when the working tree contains no unrelated user changes**

```bash
git add docs/superpowers/specs/2026-08-10-market-candle-table-collapse-design.md docs/superpowers/plans/2026-08-10-market-candle-table-collapse.md
git commit -m "docs: plan collapsed market candle data"
```
