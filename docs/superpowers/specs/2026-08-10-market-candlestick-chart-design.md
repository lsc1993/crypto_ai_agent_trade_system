# 市场页红绿 K 线图设计

## 目标

将市场详情页当前仅反映收盘价的 SVG 折线替换为交互式 OHLC K 线图：上涨为绿色、下跌为红色，同时保持现有公开行情数据来源、周期切换、空数据提示和文本 K 线表格。

## 已确认的需求

- 范围仅限 `frontend/src/features/market/MarketChart.tsx` 的市场行情展示。
- 使用加密货币通用配色：收盘价大于或等于开盘价为绿色，收盘价低于开盘价为红色。
- 复用项目已安装的 `lightweight-charts` 5.1.0，不新增第三方依赖。
- 不改变后端、行情请求、领域模型、精度校验或交易相关能力。

## 方案与取舍

采用 TradingView Lightweight Charts 的 v5 `createChart` 和 `chart.addSeries(CandlestickSeries, options)` API。该库已包含在前端依赖中，原生支持 OHLC K 线、缩放、拖动、十字光标、时间轴和价格轴；相比手写 SVG 或在 Recharts 中自定义金融图形，可避免维护坐标计算与交互状态。

不会嵌入 TradingView Widget：Widget 使用其自身数据源，无法保证继续展示本系统经后端校验的公开行情。

## 组件与数据流

`MarketChart` 继续接收 `CandleSeries` 与 `Timeframe`：

1. `toChartSeries` 继续执行唯一的显示层转换，将领域中的十进制字符串转为 JavaScript 数值；同时把 `openTime` ISO UTC 字符串转换为 Lightweight Charts 的 UTC 秒时间戳。
2. 组件在 `ref` 指向的容器中创建一个 `IChartApi`，添加 `CandlestickSeries`，并一次性调用 `setData` 写入当前周期的 OHLC 数据。
3. 各时间周期切换时，React effect 清理旧图表并创建新图表，避免残留 canvas、事件监听器和旧数据。
4. `ResizeObserver` 将容器宽度同步给图表；销毁组件时断开 observer 并调用 `chart.remove()`。
5. 图表容器保留明确的 `aria-label`；下方原有 K 线表格保留，为屏幕阅读器、数据核对和不支持 canvas 的场景提供文本内容。

## 视觉与交互

- 上涨实体、边框和影线：绿色 `#22c55e`。
- 下跌实体、边框和影线：红色 `#ef4444`。
- 图表沿用现有深色卡片背景和约 13rem 的初始高度；移除已不再使用的 SVG 网格背景。
- 保留周期标签、标题和图注；图注更新为“图表由公开行情 OHLC 数据渲染，不改变原始行情数据”。
- 行情为空时，继续显示既有 `PageState`，且不创建第三方图表实例。

## 错误处理与边界

- `Date.parse(openTime)` 无法生成有限时间戳时，转换层不向图表提供该 K 线，避免把无效时间交给第三方库；领域数据本身仍由 Zod UTC 校验保护。
- 只为浏览器渲染转换数值，不回写或改变 `CandleSeries` 的十进制字符串。
- 此图表仅用于公开市场研究，不引入账户、下单或任何实盘能力。

## 测试与验收

- 单元测试验证 OHLC、UTC 时间戳的单向显示转换及源数据不变。
- 组件测试以 Lightweight Charts 的最小 mock 验证：创建 K 线 series、写入转换数据、使用涨绿跌红选项，并在卸载时销毁图表。
- 覆盖无行情数据时不创建图表且保留现有提示。
- 运行市场图表测试、市场页测试、前端 lint、typecheck 与 build；重建 Docker Compose 后在市场页人工确认红绿 K 线、时间周期切换与详情表格。
