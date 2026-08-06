import { useQuery } from "@tanstack/react-query";
import Decimal from "decimal.js";

import { useWorkbenchApi } from "../../app/providers";
import { PnlChart } from "../analytics/PnlChart";
import type {
  PaperDecisionStats,
  PaperPerformanceSnapshot,
} from "../../domain/paper-trading";
import type { DecimalString } from "../../domain/primitives";
import { formatDecimal } from "../../shared/format";

function formatPercent(value: DecimalString): string {
  return `${formatDecimal(new Decimal(value).mul(100).toFixed(2))}%`;
}

function decisionMetricRows(
  decisionStats: PaperDecisionStats,
): ReadonlyArray<readonly [string, number]> {
  return [
    ["手动意图", decisionStats.manualIntentCount],
    ["策略评估", decisionStats.strategyEvaluationCount],
    ["无信号", decisionStats.noSignalCount],
    ["风控拒绝", decisionStats.riskRejectedCount],
    ["风控退出", decisionStats.riskExitCount],
    ["模拟订单", decisionStats.orderCount],
    ["模拟成交", decisionStats.fillCount],
  ];
}

function summaryMetricRows(
  performance: PaperPerformanceSnapshot,
): ReadonlyArray<readonly [string, string]> {
  return [
    ["初始资金", `${formatDecimal(performance.initialCash)} USDT`],
    ["当前权益", `${formatDecimal(performance.currentEquity)} USDT`],
    [
      "净盈亏",
      `${formatDecimal(performance.netPnl, { showPositiveSign: true })} USDT`,
    ],
    ["累计收益率", formatPercent(performance.returnFraction)],
    [
      "已实现盈亏",
      `${formatDecimal(performance.realizedPnl, { showPositiveSign: true })} USDT`,
    ],
    [
      "未实现盈亏",
      `${formatDecimal(performance.unrealizedPnl, { showPositiveSign: true })} USDT`,
    ],
    ["累计手续费", `${formatDecimal(performance.totalFee)} USDT`],
    ["最大回撤", `${formatDecimal(performance.maxDrawdownAmount)} USDT`],
    ["最大回撤率", formatPercent(performance.maxDrawdownFraction)],
    ["平仓胜率", formatPercent(performance.closeWinRate)],
    ["开仓成交", String(performance.openFillCount)],
    ["平仓成交", String(performance.closeFillCount)],
  ];
}

export function PaperPerformancePanel({ accountId }: { accountId: string }) {
  const api = useWorkbenchApi();
  const performanceQuery = useQuery({
    queryKey: ["paper-performance", accountId],
    queryFn: () => api.getPaperPerformance(accountId),
  });

  return (
    <section
      aria-labelledby="paper-performance-title"
      className="paper-detail-section paper-performance"
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">PERSISTED LOCAL PERFORMANCE</p>
          <h2 id="paper-performance-title">模拟盘绩效报告</h2>
        </div>
      </div>
      {performanceQuery.isPending ? (
        <p className="paper-detail-section__description" role="status">
          正在读取模拟盘绩效。
        </p>
      ) : performanceQuery.isError || performanceQuery.data === undefined ? (
        <p
          aria-label="模拟盘绩效读取失败"
          className="inline-error"
          role="alert"
        >
          无法读取模拟盘绩效，请稍后重试。
        </p>
      ) : (
        <PaperPerformanceContent performance={performanceQuery.data} />
      )}
    </section>
  );
}

function PaperPerformanceContent({
  performance,
}: {
  performance: PaperPerformanceSnapshot;
}) {
  const chartPoints = performance.equityCurve.map((point) => ({
    at: point.at,
    equity: point.equity,
    netPnl: point.netPnl,
  }));

  return (
    <>
      {performance.historyStatus === "partial" ? (
        <p className="paper-performance__history-note" role="note">
          仅覆盖迁移基线之后的可用记录。
        </p>
      ) : null}
      <dl className="paper-account-metrics paper-performance__metrics">
        {summaryMetricRows(performance).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <dl className="paper-performance__context">
        <div>
          <dt>统计起点（UTC）</dt>
          <dd>
            <time dateTime={performance.historyStartedAt}>
              {performance.historyStartedAt}
            </time>
          </dd>
        </div>
        <div>
          <dt>统计终点（UTC）</dt>
          <dd>
            <time dateTime={performance.historyEndedAt}>
              {performance.historyEndedAt}
            </time>
          </dd>
        </div>
        <div>
          <dt>生成时间（UTC）</dt>
          <dd>
            <time dateTime={performance.generatedAt}>
              {performance.generatedAt}
            </time>
          </dd>
        </div>
      </dl>
      <PnlChart points={chartPoints} />
      <section aria-labelledby="paper-decision-stats-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">DETERMINISTIC DECISIONS</p>
            <h3 id="paper-decision-stats-title">决策与执行统计</h3>
          </div>
        </div>
        <dl className="paper-account-metrics paper-performance__decision-stats">
          {decisionMetricRows(performance.decisionStats).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
