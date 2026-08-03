import type { AnalyticsSnapshot } from "../../domain/analytics";
import { formatDecimal } from "../../shared/format";

export interface KpiCardsProps {
  snapshot: AnalyticsSnapshot;
}

export function KpiCards({ snapshot }: KpiCardsProps) {
  const metrics = [
    { label: "净盈亏", value: snapshot.netPnl },
    { label: "胜率", value: snapshot.winRate },
    { label: "利润因子", value: snapshot.profitFactor },
    { label: "期望值", value: snapshot.expectancy },
    { label: "最大回撤", value: snapshot.maxDrawdown },
  ];

  return (
    <section aria-labelledby="analytics-kpi-title" className="research-panel">
      <div className="section-heading">
        <div>
          <p className="section-kicker">模拟统计</p>
          <h2 id="analytics-kpi-title">核心复盘指标</h2>
        </div>
      </div>
      <dl className="metric-list metric-list--overview">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value === null ? "不适用" : formatDecimal(metric.value)}</dd>
          </div>
        ))}
        <div>
          <dt>生成时间（UTC）</dt>
          <dd>
            <time dateTime={snapshot.generatedAt}>
              {snapshot.generatedAt}
            </time>
          </dd>
        </div>
      </dl>
      <p>
        指标直接来自模拟统计快照；杠杆不参与实际盈亏放大。
      </p>
    </section>
  );
}
