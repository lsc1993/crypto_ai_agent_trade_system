# 市场页红绿 K 线图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将市场详情页的收盘价 SVG 折线替换为可交互、涨绿跌红的 OHLC K 线图。

**Architecture:** `MarketChart` 保持为市场页面唯一的图表组件。它通过一个纯数据转换函数把经领域校验的 UTC ISO 时间和十进制字符串转换为 Lightweight Charts 5 所需的 UTC 秒时间戳及数值，再在 React effect 中创建和销毁 K 线图表。原有文本表格继续作为数据核对与无障碍备用内容。

**Tech Stack:** React 19、TypeScript 5.9、Vitest、Testing Library、`lightweight-charts` 5.1.0、Vite 8。

## Global Constraints

- 复用已安装的 `lightweight-charts` 5.1.0；不得添加生产依赖。
- 上涨 K 线全部使用 `#22c55e`，下跌 K 线全部使用 `#ef4444`。
- 领域 K 线仍使用十进制字符串；转换仅存在于浏览器显示层且不得改变输入对象。
- 保持现有公开行情接口、周期切换、空数据提示、文本表格和无账户研究边界。
- 代码变更必须遵循 TDD：先写测试、确认失败、再写最小实现。
- 不修改 `.env`、凭证、交易或真实账户配置。

---

### Task 1: 扩展图表显示数据转换

**Files:**
- Modify: `frontend/src/features/market/MarketChart.tsx:1-36`
- Test: `frontend/src/features/market/MarketChart.test.ts:1-31`

**Interfaces:**
- Consumes: `CandleSeries`，其每根 K 线带有 `openTime` ISO UTC 字符串与 `open`、`high`、`low`、`close` 十进制字符串。
- Produces: `toChartSeries(series: CandleSeries): CandlestickData<UTCTimestamp>[]`，每项含 `time`、`open`、`high`、`low`、`close` 数值。

- [x] **Step 1: 写入失败的时间戳转换测试**

```typescript
expect(chartSeries[0]).toMatchObject({
  time: 1736935200,
  open: 67000,
  high: 68000,
  low: 66800,
  close: 67600,
});
expect(source).toEqual(original);
```

- [x] **Step 2: 运行测试确认因当前输出 ISO 字符串而失败**

Run: `npm run test -- --run src/features/market/MarketChart.test.ts`

Expected: FAIL，`time` 的期望 UTC 秒值与当前 ISO 字符串不相等。

- [x] **Step 3: 实现最小的单向转换**

```typescript
function toUtcTimestamp(isoTime: string): UTCTimestamp {
  return Math.floor(Date.parse(isoTime) / 1_000) as UTCTimestamp;
}

export function toChartSeries(series: CandleSeries): CandlestickData<UTCTimestamp>[] {
  return series.candles.map((candle) => ({
    time: toUtcTimestamp(candle.openTime),
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  }));
}
```

- [x] **Step 4: 重新运行转换测试**

Run: `npm run test -- --run src/features/market/MarketChart.test.ts`

Expected: PASS，且领域对象仍保持十进制字符串。

- [x] **Step 5: 提交本任务文件**

```powershell
git add -- frontend/src/features/market/MarketChart.tsx frontend/src/features/market/MarketChart.test.ts
git commit -m "feat: map market candles for chart rendering"
```

### Task 2: 用 Lightweight Charts 渲染红绿 K 线

**Files:**
- Modify: `frontend/src/features/market/MarketChart.tsx:1-145`
- Create: `frontend/src/features/market/MarketChart.component.test.tsx`

**Interfaces:**
- Consumes: `MarketChartProps` 与 Task 1 生成的 `CandlestickData<UTCTimestamp>[]`。
- Produces: 在 `.market-chart__canvas` 容器中创建的 `IChartApi`；图表 series 使用 `CandlestickSeries`，调用 `setData` 后显示所有 OHLC 数据。

- [x] **Step 1: 写入失败的组件生命周期测试**

```tsx
render(<MarketChart series={series} timeframe="1h" />);

expect(createChart).toHaveBeenCalledTimes(1);
expect(addSeries).toHaveBeenCalledWith(CandlestickSeries, {
  upColor: "#22c55e",
  downColor: "#ef4444",
  borderUpColor: "#22c55e",
  borderDownColor: "#ef4444",
  wickUpColor: "#22c55e",
  wickDownColor: "#ef4444",
});
expect(setData).toHaveBeenCalledWith(toChartSeries(series));
```

测试 mock `createChart`、`addSeries`、`setData`、`timeScale().fitContent()` 与 `remove()`，并在 `unmount()` 后断言 `remove()` 被调用一次。

- [x] **Step 2: 运行组件测试确认失败**

Run: `npm run test -- --run src/features/market/MarketChart.component.test.tsx`

Expected: FAIL，当前组件没有导入或调用 Lightweight Charts。

- [x] **Step 3: 实现最小图表生命周期**

```tsx
const containerRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  const container = containerRef.current;
  if (container === null || series === undefined || series.candles.length === 0) return;
  const chart = createChart(container, { /* 深色布局和时间轴 */ });
  const candleSeries = chart.addSeries(CandlestickSeries, CANDLESTICK_COLORS);
  candleSeries.setData(toChartSeries(series));
  chart.timeScale().fitContent();
  return () => chart.remove();
}, [series]);
```

使用 `ResizeObserver` 将容器的 `contentRect.width` 传给 `chart.applyOptions({ width })`，并在 cleanup 中调用 `disconnect()`；图表容器设置 `aria-label`，而表格继续渲染。

- [x] **Step 4: 运行组件与转换测试**

Run: `npm run test -- --run src/features/market/MarketChart.test.ts src/features/market/MarketChart.component.test.tsx`

Expected: PASS，涨绿跌红配置、数据写入、销毁与转换均通过。

- [x] **Step 5: 提交本任务文件**

```powershell
git add -- frontend/src/features/market/MarketChart.tsx frontend/src/features/market/MarketChart.component.test.tsx
git commit -m "feat: render market candlesticks"
```

### Task 3: 调整图表容器样式并验证页面集成

**Files:**
- Modify: `frontend/src/styles/index.css:549-572`
- Test: `frontend/src/features/market/MarketPage.test.tsx`

**Interfaces:**
- Consumes: `.market-chart__canvas` 图表容器与 `MarketChart` 的既有标签、表格和空态结构。
- Produces: 适合 Canvas 自适应宽度的深色图表容器，初始高度为 `13rem`，同时保留窄屏布局。

- [x] **Step 1: 写入失败的市场页可访问内容测试**

```tsx
expect(await screen.findByLabelText("1h K 线图，共 2 个数据点")).toBeInTheDocument();
expect(screen.getByText("1h K 线文本数据")).toBeInTheDocument();
```

- [x] **Step 2: 运行测试确认失败**

Run: `npm run test -- --run src/features/market/MarketPage.test.tsx`

Expected: FAIL，当前折线 SVG 使用的是“收盘价走势”标签，且没有 K 线图容器。

- [x] **Step 3: 删除旧 SVG 样式并添加图表容器样式**

```css
.market-chart__canvas {
  width: 100%;
  height: 13rem;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  background: #09141e;
}
```

更新图注，使其准确表明 OHLC 图表仅为浏览器显示转换。

- [x] **Step 4: 运行市场页与市场图表测试**

Run: `npm run test -- --run src/features/market/MarketPage.test.tsx src/features/market/MarketChart.test.ts src/features/market/MarketChart.component.test.tsx`

Expected: PASS，页面中的 K 线容器和文本表格同时存在，空态测试继续通过。

- [x] **Step 5: 提交本任务文件**

```powershell
git add -- frontend/src/styles/index.css frontend/src/features/market/MarketPage.test.tsx
git commit -m "style: fit market candlestick chart"
```

### Task 4: 质量、构建与 Docker 页面验收

**Files:**
- Verify only: `frontend/src/features/market/MarketChart.tsx`
- Verify only: `frontend/src/features/market/MarketChart.component.test.tsx`
- Verify only: `frontend/src/styles/index.css`

**Interfaces:**
- Consumes: 已完成的市场页 K 线图实现。
- Produces: 可在当前 Docker Compose 前端中展示并可交互的红绿 K 线图。

- [x] **Step 1: 运行静态检查和完整前端测试**

Run:

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Expected: 所有命令退出码为 0。

- [x] **Step 2: 重建当前 Docker Compose 服务**

Run:

```powershell
docker compose up -d --build
```

Expected: `api`、`frontend`、`postgres` 服务健康；前端构建包含新 K 线实现。

- [x] **Step 3: 浏览器验收市场页**

打开 `/market/BTCUSDT`，检查以下内容：

- 存在绿色上涨和红色下跌 K 线实体及影线；
- 悬停显示十字光标，滚轮缩放与拖动时间轴可用；
- 切换 1h、4h、1d 周期后图表和文本表格同步更新；
- 页面无控制台错误，窄屏下图表未溢出。

- [x] **Step 4: 提交本任务文件**

```powershell
git add -- frontend/src/features/market/MarketChart.tsx frontend/src/features/market/MarketChart.test.ts frontend/src/features/market/MarketChart.component.test.tsx frontend/src/features/market/MarketPage.test.tsx frontend/src/styles/index.css
git commit -m "test: verify market candlestick chart"
```
