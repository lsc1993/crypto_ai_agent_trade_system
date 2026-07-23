import Decimal from "decimal.js";

import type { EquityPoint } from "../../domain/analytics";

export interface EquityChartPoint {
  at: string;
  equity: number;
  netPnl: number;
}

// 该适配器仅服务于图形显示；十进制字符串仍是业务与表格的唯一来源。
export function toEquityChartSeries(
  points: EquityPoint[],
): EquityChartPoint[] {
  return points.map((point) => ({
    at: point.at,
    equity: new Decimal(point.equity).toNumber(),
    netPnl: new Decimal(point.netPnl).toNumber(),
  }));
}
