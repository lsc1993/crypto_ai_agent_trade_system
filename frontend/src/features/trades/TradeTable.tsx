import { Link } from "react-router-dom";

import type { Trade } from "../../domain/trade";

interface TradeTableProps {
  trades: Trade[];
}

const directionLabels = {
  long: "多向",
  short: "空向",
} as const;

const horizonLabels = {
  short_term: "短期",
  medium_term: "中期",
} as const;

const statusLabels = {
  open: "记录中",
  closed: "已结束",
} as const;

export function TradeTable({ trades }: TradeTableProps) {
  return (
    <div className="table-scroll">
      <table className="market-table" aria-label="交易日志记录">
        <thead>
          <tr>
            <th scope="col">标的</th>
            <th scope="col">方向</th>
            <th scope="col">周期</th>
            <th scope="col">状态</th>
            <th scope="col">净盈亏</th>
            <th scope="col">关联报告 ID</th>
            <th scope="col">交易腿数</th>
            <th scope="col">开始时间（UTC）</th>
            <th scope="col">记录操作</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td>{trade.symbol}</td>
              <td>{directionLabels[trade.direction]}</td>
              <td>{horizonLabels[trade.horizon]}</td>
              <td>{statusLabels[trade.status]}</td>
              <td>{trade.netPnl}</td>
              <td>{trade.linkedReportId ?? "未关联"}</td>
              <td>{trade.legs.length}</td>
              <td>
                <time dateTime={trade.openedAt}>{trade.openedAt}</time>
              </td>
              <td>
                <Link
                  className="text-link"
                  to={`/trades/${encodeURIComponent(trade.id)}/edit`}
                >
                  编辑日志
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
