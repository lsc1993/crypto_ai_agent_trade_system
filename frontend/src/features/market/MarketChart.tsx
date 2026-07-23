import { PageState } from "../../components/common/PageState";
import type { CandleSeries } from "../../domain/market";
import type { Timeframe } from "../../domain/primitives";
import {
  formatMarketPrice,
  formatMarketVolume,
} from "../../shared/format";

export interface ChartCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// The required one-way display adapter is intentionally exported beside its chart.
// eslint-disable-next-line react-refresh/only-export-components
export function toChartSeries(series: CandleSeries): ChartCandle[] {
  return series.candles.map((candle) => ({
    time: candle.openTime,
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
    volume: Number(candle.volume),
  }));
}

function buildClosePolyline(points: ChartCandle[]): string {
  if (points.length === 0) {
    return "";
  }
  const closes = points.map((point) => point.close);
  const minimum = Math.min(...closes);
  const maximum = Math.max(...closes);
  const range = maximum - minimum || 1;
  const width = 600;
  const height = 180;

  return points
    .map((point, index) => {
      const x =
        points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
      const y = height - ((point.close - minimum) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
}

export interface MarketChartProps {
  series: CandleSeries | undefined;
  timeframe: Timeframe;
}

export function MarketChart({
  series,
  timeframe,
}: MarketChartProps) {
  if (series === undefined || series.candles.length === 0) {
    return (
      <section
        className="research-panel market-chart"
        role="tabpanel"
        id="market-timeframe-panel"
        aria-labelledby={`market-timeframe-tab-${timeframe}`}
      >
        <h2>K 线图表</h2>
        <PageState
          state="empty"
          message="当前周期暂无 K 线数据，请选择其他周期。"
        />
      </section>
    );
  }

  const chartPoints = toChartSeries(series);
  const polyline = buildClosePolyline(chartPoints);

  return (
    <section
      className="research-panel market-chart"
      role="tabpanel"
      id="market-timeframe-panel"
      aria-labelledby={`market-timeframe-tab-${timeframe}`}
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">{series.timeframe} DISPLAY SERIES</p>
          <h2>K 线图表</h2>
        </div>
      </div>
      <figure className="market-chart__figure">
        <svg
          className="market-chart__visual"
          role="img"
          aria-label={`${series.timeframe} 收盘价走势，共 ${series.candles.length} 个数据点`}
          viewBox="0 0 600 180"
          preserveAspectRatio="none"
        >
          <polyline
            points={polyline}
            fill="none"
            stroke="currentColor"
            strokeWidth="5"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        <figcaption>
          图形仅将领域十进制字符串单向转换为浏览器显示数值；原始行情数据保持不变。
        </figcaption>
      </figure>
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
                <td>
                  <time dateTime={candle.openTime}>{candle.openTime}</time>
                </td>
                <td>{formatMarketPrice(candle.open)}</td>
                <td>{formatMarketPrice(candle.high)}</td>
                <td>{formatMarketPrice(candle.low)}</td>
                <td>{formatMarketPrice(candle.close)}</td>
                <td>{formatMarketVolume(candle.volume)}</td>
                <td>
                  <time dateTime={candle.closeTime}>
                    {candle.closeTime}
                  </time>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
