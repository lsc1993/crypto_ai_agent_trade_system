import { useState } from "react";

import type { TradeCalendarPoint } from "../../domain/analytics";
import { formatDecimal } from "../../shared/format";

export interface TradeCalendarProps {
  points: TradeCalendarPoint[];
}

function utcDate(point: TradeCalendarPoint): string {
  return point.at.slice(0, 10);
}

export function TradeCalendar({ points }: TradeCalendarProps) {
  const [selectedAt, setSelectedAt] = useState<string | null>(null);
  const selected = points.find((point) => point.at === selectedAt);

  return (
    <section aria-labelledby="trade-calendar-title" className="research-panel">
      <div className="section-heading">
        <div>
          <p className="section-kicker">按 UTC 日期</p>
          <h2 id="trade-calendar-title">交易日历</h2>
        </div>
      </div>
      {points.length === 0 ? (
        <p>当前筛选条件下暂无交易日历数据。</p>
      ) : (
        <div aria-label="交易日历日期选择" role="group">
          {points.map((point) => {
            const date = utcDate(point);
            const isSelected = point.at === selectedAt;
            return (
              <button
                aria-label={`选择 ${date} UTC`}
                aria-pressed={isSelected}
                className="secondary-action"
                key={point.at}
                type="button"
                onClick={() => {
                  setSelectedAt(point.at);
                }}
              >
                {date}
              </button>
            );
          })}
        </div>
      )}
      {selected === undefined ? null : (
        <p role="status">
          已选择 UTC 日期：{utcDate(selected)}。净盈亏：
          {formatDecimal(selected.netPnl)}；交易笔数：
          {String(selected.tradeCount)}。
        </p>
      )}
      <div className="table-scroll">
        <table aria-label="交易日历文本数据" className="market-table">
          <caption>交易日历文本数据</caption>
          <thead>
            <tr>
              <th scope="col">UTC 日期</th>
              <th scope="col">净盈亏</th>
              <th scope="col">交易笔数</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.at}>
                <td>
                  <time dateTime={point.at}>{utcDate(point)}</time>
                </td>
                <td>{formatDecimal(point.netPnl)}</td>
                <td>{String(point.tradeCount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
