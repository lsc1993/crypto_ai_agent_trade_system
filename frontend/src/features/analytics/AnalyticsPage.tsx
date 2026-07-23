import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import {
  analyticsFiltersSchema,
  type AnalyticsFilters,
} from "../../domain/analytics";
import { AnalyticsFiltersPanel } from "./AnalyticsFilters";
import { KpiCards } from "./KpiCards";
import { PnlChart } from "./PnlChart";
import { TradeCalendar } from "./TradeCalendar";

function parseAnalyticsFilters(
  filters: AnalyticsFilters,
): AnalyticsFilters {
  const parsed = analyticsFiltersSchema.safeParse(filters);
  if (!parsed.success) {
    throw new Error("Analytics filters failed validation");
  }
  return parsed.data;
}

export function AnalyticsPage() {
  const api = useWorkbenchApi();
  const [filters, setFilters] = useState<AnalyticsFilters>({});
  const analyticsQuery = useQuery({
    queryKey: ["analytics", filters],
    queryFn: () => api.getAnalytics(parseAnalyticsFilters(filters)),
  });

  let content;
  if (analyticsQuery.isPending) {
    content = <PageState state="loading" />;
  } else if (analyticsQuery.isError) {
    content = (
      <PageState
        state="error"
        message="无法读取复盘统计，请稍后重试。"
      />
    );
  } else if (analyticsQuery.data === undefined) {
    content = (
      <PageState
        state="unavailable"
        message="复盘统计数据暂不可用，请稍后重试。"
      />
    );
  } else if (
    analyticsQuery.data.equityCurve.length === 0 &&
    analyticsQuery.data.tradeCalendar.length === 0
  ) {
    content = (
      <PageState
        state="empty"
        message="当前筛选条件下暂无可复盘的交易统计。"
      />
    );
  } else {
    content = (
      <div className="analytics-page__content">
        <KpiCards snapshot={analyticsQuery.data} />
        <PnlChart points={analyticsQuery.data.equityCurve} />
        <TradeCalendar points={analyticsQuery.data.tradeCalendar} />
      </div>
    );
  }

  return (
    <section className="research-page analytics-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">模拟复盘</p>
          <h1>复盘统计</h1>
          <p>
            统计仅来自结构化模拟交易日志，用于复盘研究，不连接交易所或真实账户。
          </p>
        </div>
      </header>
      <AnalyticsFiltersPanel value={filters} onApply={setFilters} />
      {content}
    </section>
  );
}
