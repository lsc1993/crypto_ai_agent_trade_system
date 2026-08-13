import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type { Symbol, Timeframe } from "../../domain/primitives";
import { WorkbenchHttpError } from "../../shared/api/http-transport";
import {
  formatDailyChange,
  formatMarketPrice,
  formatMarketVolume,
} from "../../shared/format";
import { DerivativePanel } from "./DerivativePanel";
import { MarketCandleDataTable } from "./MarketCandleDataTable";
import { MarketChart } from "./MarketChart";
import { NewsTimeline } from "./NewsTimeline";
import { TimeframeTabs } from "./TimeframeTabs";
import { MARKET_TIMEFRAMES } from "./market-timeframes";

function parseSupportedSymbol(value: string | undefined): Symbol | undefined {
  return value === "BTCUSDT" || value === "ETHUSDT"
    ? value
    : undefined;
}

export function MarketPage() {
  const api = useWorkbenchApi();
  const navigate = useNavigate();
  const params = useParams();
  const symbol = parseSupportedSymbol(params.symbol);
  const [selectedTimeframe, setSelectedTimeframe] =
    useState<Timeframe>("1h");
  const marketQuery = useQuery({
    queryKey: ["market", symbol],
    enabled: symbol !== undefined,
    queryFn: () => {
      if (symbol === undefined) {
        throw new Error("Unsupported market symbol");
      }
      return api.getMarket({
        symbol,
        timeframes: [...MARKET_TIMEFRAMES],
      });
    },
  });
  const reportMutation = useMutation({
    mutationKey: ["start-report", symbol],
    mutationFn: () => {
      if (symbol === undefined) {
        throw new Error("Unsupported report symbol");
      }
      return api.startReport({ symbol });
    },
    onSuccess: ({ reportId }) => {
      if (reportId !== undefined) {
        void navigate(`/reports/${encodeURIComponent(reportId)}`);
      }
    },
  });

  if (symbol === undefined) {
    return (
      <PageState
        state="unavailable"
        message="当前仅支持 BTCUSDT 与 ETHUSDT 研究标的。"
      />
    );
  }

  if (marketQuery.isPending) {
    return <PageState state="loading" />;
  }

  if (marketQuery.isError) {
    const isPublicMarketUnavailable =
      marketQuery.error instanceof WorkbenchHttpError &&
      marketQuery.error.code.startsWith("market_data_");
    return (
      <PageState
        state="error"
        message={
          isPublicMarketUnavailable
            ? "公开行情暂不可用，请检查后端服务、网络或数据源状态后重试。"
            : "无法读取市场研究数据，请稍后重试。"
        }
      />
    );
  }

  const market = marketQuery.data;
  const selectedSeries = market.series.find(
    (series) => series.timeframe === selectedTimeframe,
  );

  return (
    <section className="research-page market-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">公开市场研究 · 无账户模式</p>
          <h1>{symbol} 市场详情</h1>
          <p>
            查看可追溯行情、K 线与来源信息。报告、日志与复盘仅用于研究，不连接账户，也不提供交易执行能力。
          </p>
        </div>
        <nav className="symbol-switcher" aria-label="研究标的切换">
          {(["BTCUSDT", "ETHUSDT"] as const).map((candidate) => (
            <Link
              className="symbol-switcher__link"
              aria-current={candidate === symbol ? "page" : undefined}
              key={candidate}
              to={`/market/${candidate}`}
            >
              {candidate}
            </Link>
          ))}
        </nav>
      </header>

      <section
        className="market-overview"
        aria-labelledby="market-overview-title"
      >
        <div className="section-heading">
          <div>
            <p className="section-kicker">MARKET OVERVIEW</p>
            <h2 id="market-overview-title">市场概览</h2>
          </div>
        </div>
        <dl className="metric-list metric-list--overview">
          <div>
            <dt>价格</dt>
            <dd>{formatMarketPrice(market.summary.price)}</dd>
          </div>
          <div>
            <dt>24 小时涨跌</dt>
            <dd>{formatDailyChange(market.summary.change24h)}</dd>
          </div>
          <div>
            <dt>24 小时成交量</dt>
            <dd>{formatMarketVolume(market.summary.volume24h)}</dd>
          </div>
        </dl>
      </section>

      <div className="market-page__controls">
        <TimeframeTabs
          value={selectedTimeframe}
          onValueChange={setSelectedTimeframe}
        />
        <div className="research-action">
          <button
            className="primary-action"
            type="button"
            disabled={reportMutation.isPending}
            onClick={() => {
              reportMutation.mutate();
            }}
          >
            生成 AI 研究报告
          </button>
          {reportMutation.isPending ? (
            <p role="status">正在创建研究任务，请稍候。</p>
          ) : null}
          {reportMutation.isSuccess ? (
            <p role="status">
              研究任务已创建：{reportMutation.data.analysisId}
            </p>
          ) : null}
          {reportMutation.isError ? (
            <p className="inline-error" role="alert">
              研究任务创建失败，请稍后重试。
            </p>
          ) : null}
        </div>
      </div>

      <div className="market-page__grid">
        <MarketChart
          series={selectedSeries}
          timeframe={selectedTimeframe}
        />
        <DerivativePanel summary={market.summary} />
      </div>
      <NewsTimeline
        news={market.news}
        emptyMessage={
          market.summary.freshness.source === "binance_usdm_public_rest"
            ? "Binance 公开行情模式尚未配置新闻源。"
          : undefined
        }
      />
      {selectedSeries !== undefined && selectedSeries.candles.length > 0 ? (
        <details
          className="market-candle-data"
          aria-label={`${selectedSeries.timeframe} K 线文本数据`}
        >
          <summary>查看 {selectedSeries.timeframe} K 线文本数据</summary>
          <MarketCandleDataTable series={selectedSeries} />
        </details>
      ) : null}
    </section>
  );
}
