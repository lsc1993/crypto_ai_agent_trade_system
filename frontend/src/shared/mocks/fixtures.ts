import {
  analyticsSnapshotSchema,
} from "../../domain/analytics";
import {
  dashboardSnapshotSchema,
  marketDetailSchema,
  marketSummarySchema,
} from "../../domain/market";
import { newsItemSchema } from "../../domain/news";
import {
  analysisReportSchema,
  analysisReportSummarySchema,
} from "../../domain/report";
import {
  tradeDraftSchema,
  tradeSchema,
} from "../../domain/trade";

export const mockNews = [
  newsItemSchema.parse({
    id: "news-001",
    title: "示例市场基础设施维护公告",
    summary: "这是离线 Mock 摘要，仅用于验证工作台的数据契约。",
    source: "Mock Research Feed",
    sourceUrl: "https://example.com/mock-news-001",
    publishedAt: "2025-01-14T08:00:00Z",
    fetchedAt: "2025-01-14T08:05:00Z",
    symbols: ["BTCUSDT", "ETHUSDT"],
  }),
];

export const mockReports = [
  analysisReportSchema.parse({
    id: "report-btc-001",
    analysisId: "analysis-btc-001",
    symbol: "BTCUSDT",
    status: "completed",
    title: "BTCUSDT 离线研究样例",
    summary: "用于界面和 API 契约验证的确定性 Mock 报告。",
    createdAt: "2025-01-15T10:00:00Z",
    dataCutoffAt: "2025-01-15T09:55:00Z",
    facts: ["示例价格和成交量来自固定 Mock 数据。"],
    inferences: ["该段落仅演示推断与事实分离。"],
    risks: ["固定样例不反映当前市场。"],
    limitations: ["没有访问交易所、账户或模型服务。"],
    evidence: [
      {
        id: "evidence-btc-001",
        symbol: "BTCUSDT",
        source: "Mock Research Feed",
        sourceUrl: "https://example.com/mock-evidence-btc-001",
        observedAt: "2025-01-15T09:55:00Z",
        summary: "固定的离线证据摘要。",
      },
    ],
  }),
  analysisReportSchema.parse({
    id: "report-eth-001",
    analysisId: "analysis-eth-001",
    symbol: "ETHUSDT",
    status: "degraded",
    title: "ETHUSDT 离线降级样例",
    summary: "演示数据缺失时的明确降级状态。",
    createdAt: "2025-01-15T11:00:00Z",
    dataCutoffAt: "2025-01-15T10:45:00Z",
    facts: ["部分固定 Mock 指标被标记为过期。"],
    inferences: [],
    risks: ["不可根据缺失数据形成方向性结论。"],
    limitations: ["这不是实时分析，也不是交易指令。"],
    evidence: [
      {
        id: "evidence-eth-001",
        symbol: "ETHUSDT",
        source: "Mock Research Feed",
        sourceUrl: "https://example.com/mock-evidence-eth-001",
        observedAt: "2025-01-15T10:45:00Z",
        summary: "固定的离线降级证据摘要。",
      },
    ],
  }),
];

export const mockReportSummaries = mockReports.map((report) =>
  analysisReportSummarySchema.parse(report),
);

export const mockMarketSummaries = [
  marketSummarySchema.parse({
    symbol: "BTCUSDT",
    price: "67890.12",
    change24h: "1.25",
    volume24h: "3250000000.50",
    fundingRate: "0.0001",
    openInterest: "1280000000",
    freshness: {
      status: "fresh",
      source: "Deterministic Mock",
      observedAt: "2025-01-15T12:00:00Z",
      fetchedAt: "2025-01-15T12:00:05Z",
    },
  }),
  marketSummarySchema.parse({
    symbol: "ETHUSDT",
    price: "3456.78",
    change24h: "-0.75",
    volume24h: "1850000000",
    fundingRate: "-0.00005",
    openInterest: "720000000",
    freshness: {
      status: "stale",
      source: "Deterministic Mock",
      observedAt: "2025-01-15T11:45:00Z",
      fetchedAt: "2025-01-15T12:00:05Z",
    },
  }),
];

export const mockMarketDetails = [
  marketDetailSchema.parse({
    summary: mockMarketSummaries[0],
    series: [
      {
        timeframe: "1h",
        candles: [
          {
            symbol: "BTCUSDT",
            timeframe: "1h",
            openTime: "2025-01-15T10:00:00Z",
            closeTime: "2025-01-15T10:59:59Z",
            open: "67000",
            high: "68000",
            low: "66800",
            close: "67600",
            volume: "1250.5",
          },
          {
            symbol: "BTCUSDT",
            timeframe: "1h",
            openTime: "2025-01-15T11:00:00Z",
            closeTime: "2025-01-15T11:59:59Z",
            open: "67600",
            high: "68100",
            low: "67400",
            close: "67890.12",
            volume: "1100",
          },
        ],
      },
    ],
    news: mockNews,
  }),
  marketDetailSchema.parse({
    summary: mockMarketSummaries[1],
    series: [
      {
        timeframe: "1h",
        candles: [
          {
            symbol: "ETHUSDT",
            timeframe: "1h",
            openTime: "2025-01-15T11:00:00Z",
            closeTime: "2025-01-15T11:59:59Z",
            open: "3475",
            high: "3482",
            low: "3430",
            close: "3456.78",
            volume: "8450",
          },
        ],
      },
    ],
    news: mockNews,
  }),
];

export const mockTradeDraft = tradeDraftSchema.parse({
  symbol: "BTCUSDT",
  direction: "long",
  horizon: "short_term",
  labels: ["计划内"],
  linkedReportId: "report-btc-001",
  leverage: "2",
  legs: [
    {
      id: "leg-draft-open-001",
      action: "open",
      executedAt: "2025-01-16T01:00:00Z",
      price: "68000",
      quantity: "0.01",
      fee: "0.25",
    },
  ],
  fundingFee: "0",
  thesis: "固定 Mock 交易草稿。",
  review: "",
});

export const mockTrades = [
  tradeSchema.parse({
    symbol: "BTCUSDT",
    direction: "long",
    horizon: "short_term",
    labels: ["复盘样例"],
    linkedReportId: "report-btc-001",
    leverage: "2",
    legs: [
      {
        id: "leg-trade-001-open",
        action: "open",
        executedAt: "2025-01-10T01:00:00Z",
        price: "65000",
        quantity: "0.01",
        fee: "0.25",
      },
      {
        id: "leg-trade-001-close",
        action: "close",
        executedAt: "2025-01-11T01:00:00Z",
        price: "66000",
        quantity: "0.01",
        fee: "0.25",
      },
    ],
    fundingFee: "0.10",
    thesis: "固定 Mock 入场依据。",
    review: "固定 Mock 复盘结论。",
    id: "trade-001",
    status: "closed",
    netPnl: "9.40",
    openedAt: "2025-01-10T01:00:00Z",
    closedAt: "2025-01-11T01:00:00Z",
    createdAt: "2025-01-10T01:05:00Z",
    updatedAt: "2025-01-11T01:05:00Z",
  }),
];

export const mockAnalytics = analyticsSnapshotSchema.parse({
  netPnl: "9.40",
  winRate: "1",
  profitFactor: "0",
  expectancy: "9.40",
  maxDrawdown: "0",
  equityCurve: [
    {
      at: "2025-01-11T01:05:00Z",
      equity: "9.40",
      netPnl: "9.40",
    },
  ],
  tradeCalendar: [
    {
      at: "2025-01-11T00:00:00Z",
      netPnl: "9.40",
      tradeCount: 1,
    },
  ],
  generatedAt: "2025-01-15T12:05:00Z",
});

export const mockDashboard = dashboardSnapshotSchema.parse({
  markets: mockMarketSummaries,
  news: mockNews,
  recentReports: mockReportSummaries,
  generatedAt: "2025-01-15T12:05:00Z",
});
