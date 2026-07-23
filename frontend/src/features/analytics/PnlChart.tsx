import type { EquityPoint } from "../../domain/analytics";
import { formatDecimal } from "../../shared/format";
import {
  toEquityChartSeries,
  type EquityChartPoint,
} from "./equity-chart-series";

export interface PnlChartProps {
  points: EquityPoint[];
}

function toPolylinePoints(series: EquityChartPoint[]): string {
  if (series.length === 0) {
    return "";
  }

  const equityValues = series.map((point) => point.equity);
  const lowest = Math.min(...equityValues);
  const highest = Math.max(...equityValues);
  const range = highest - lowest || 1;
  const horizontalSteps = Math.max(series.length - 1, 1);

  return series
    .map((point, index) => {
      const x = (index / horizontalSteps) * 100;
      const y = 100 - ((point.equity - lowest) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");
}

export function PnlChart({ points }: PnlChartProps) {
  const series = toEquityChartSeries(points);

  return (
    <section aria-labelledby="pnl-chart-title" className="research-panel">
      <div className="section-heading">
        <div>
          <p className="section-kicker">仅用于显示</p>
          <h2 id="pnl-chart-title">权益曲线</h2>
        </div>
      </div>
      {series.length === 0 ? (
        <p>当前筛选条件下暂无权益曲线数据。</p>
      ) : (
        <figure className="market-chart__figure">
          <svg
            aria-label={`权益曲线，共 ${String(series.length)} 个数据点`}
            className="market-chart__visual"
            preserveAspectRatio="none"
            role="img"
            viewBox="0 0 100 100"
          >
            <polyline
              fill="none"
              points={toPolylinePoints(series)}
              stroke="currentColor"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          <figcaption>
            图形仅作显示适配，不会改变或保存原始十进制统计数据。
          </figcaption>
        </figure>
      )}
      <div className="table-scroll">
        <table aria-label="权益曲线文本数据" className="market-table">
          <caption>权益曲线文本数据</caption>
          <thead>
            <tr>
              <th scope="col">UTC 时间</th>
              <th scope="col">权益</th>
              <th scope="col">净盈亏</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={`${point.at}-${String(index)}`}>
                <td>
                  <time dateTime={point.at}>{point.at}</time>
                </td>
                <td>{formatDecimal(point.equity)}</td>
                <td>{formatDecimal(point.netPnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
