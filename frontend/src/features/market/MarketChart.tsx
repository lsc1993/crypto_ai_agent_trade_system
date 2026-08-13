import { CandlestickSeries, ColorType, createChart } from "lightweight-charts";
import type { CandlestickData, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { PageState } from "../../components/common/PageState";
import type { CandleSeries } from "../../domain/market";
import type { Timeframe } from "../../domain/primitives";

export type ChartCandle = CandlestickData<UTCTimestamp>;

function toUtcTimestamp(value: string): UTCTimestamp {
  return Math.floor(Date.parse(value) / 1_000) as UTCTimestamp;
}

// 必需的单向显示适配器与图表置于同一模块，限制数值转换仅用于显示。
// eslint-disable-next-line react-refresh/only-export-components
export function toChartSeries(series: CandleSeries): ChartCandle[] {
  return series.candles.map((candle) => ({
    time: toUtcTimestamp(candle.openTime),
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  }));
}

const CANDLESTICK_COLORS = {
  upColor: "#22c55e",
  downColor: "#ef4444",
  borderUpColor: "#22c55e",
  borderDownColor: "#ef4444",
  wickUpColor: "#22c55e",
  wickDownColor: "#ef4444",
};

export interface MarketChartProps {
  series: CandleSeries | undefined;
  timeframe: Timeframe;
}

export function MarketChart({
  series,
  timeframe,
}: MarketChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const chartContainer = chartContainerRef.current;
    if (
      chartContainer === null ||
      series === undefined ||
      series.candles.length === 0
    ) {
      return;
    }

    const chart = createChart(chartContainer, {
      width: chartContainer.clientWidth,
      height: 208,
      layout: {
        background: { type: ColorType.Solid, color: "#09141e" },
        textColor: "#aebdcc",
      },
      grid: {
        vertLines: { color: "rgb(41 65 87 / 28%)" },
        horzLines: { color: "rgb(41 65 87 / 28%)" },
      },
      rightPriceScale: {
        borderColor: "#294157",
      },
      timeScale: {
        borderColor: "#294157",
        timeVisible: true,
        secondsVisible: false,
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, CANDLESTICK_COLORS);
    candleSeries.setData(toChartSeries(series));
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) {
        chart.applyOptions({ width: Math.floor(entry.contentRect.width) });
      }
    });
    resizeObserver.observe(chartContainer);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [series]);

  if (series === undefined || series.candles.length === 0) {
    return (
      <section
        className="research-panel market-chart"
        role="tabpanel"
        id="market-timeframe-panel"
        aria-labelledby={`market-timeframe-tab-${timeframe}`}
        tabIndex={0}
      >
        <h2>K 线图表</h2>
        <PageState
          state="empty"
          message="当前周期暂无 K 线数据，请选择其他周期。"
        />
      </section>
    );
  }

  return (
    <section
      className="research-panel market-chart"
      role="tabpanel"
      id="market-timeframe-panel"
      aria-labelledby={`market-timeframe-tab-${timeframe}`}
      tabIndex={0}
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">{series.timeframe} DISPLAY SERIES</p>
          <h2>K 线图表</h2>
        </div>
      </div>
      <figure className="market-chart__figure">
        <div
          className="market-chart__canvas"
          ref={chartContainerRef}
          role="img"
          aria-label={`${series.timeframe} K 线图，共 ${series.candles.length} 个数据点`}
        />
        <figcaption>
          图表由公开行情 OHLC 数据渲染，仅作浏览器显示转换；原始行情数据保持不变。
        </figcaption>
      </figure>
    </section>
  );
}
