import type { CandleSeries } from "../../domain/market";
import {
  formatMarketPrice,
  formatMarketVolume,
} from "../../shared/format";

export function MarketCandleDataTable({
  series,
}: {
  series: CandleSeries;
}) {
  return (
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
                <time dateTime={candle.closeTime}>{candle.closeTime}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
