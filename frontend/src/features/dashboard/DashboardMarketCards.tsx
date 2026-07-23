import { Link } from "react-router-dom";

import { DataFreshnessBadge } from "../../components/common/DataFreshnessBadge";
import type { MarketSummary } from "../../domain/market";
import {
  formatDailyChange,
  formatFundingRate,
  formatMarketPrice,
  formatMarketVolume,
  formatOpenInterest,
} from "../../shared/format";

export interface DashboardMarketCardsProps {
  markets: MarketSummary[];
}

export function DashboardMarketCards({
  markets,
}: DashboardMarketCardsProps) {
  return (
    <div className="market-card-grid">
      {markets.map((market) => (
        <article
          className="market-card"
          aria-label={`${market.symbol} 市场摘要`}
          key={market.symbol}
        >
          <header className="market-card__header">
            <div>
              <p className="section-kicker">永续合约观察</p>
              <h3>{market.symbol}</h3>
            </div>
            <Link
              className="market-card__link"
              to={`/market/${market.symbol}`}
            >
              查看市场详情
            </Link>
          </header>
          <dl className="metric-list">
            <div>
              <dt>价格</dt>
              <dd>{formatMarketPrice(market.price)}</dd>
            </div>
            <div>
              <dt>24 小时涨跌</dt>
              <dd>{formatDailyChange(market.change24h)}</dd>
            </div>
            <div>
              <dt>24 小时成交量</dt>
              <dd>{formatMarketVolume(market.volume24h)}</dd>
            </div>
            <div>
              <dt>资金费率</dt>
              <dd>{formatFundingRate(market.fundingRate)}</dd>
            </div>
            <div>
              <dt>未平仓量</dt>
              <dd>{formatOpenInterest(market.openInterest)}</dd>
            </div>
          </dl>
          <DataFreshnessBadge {...market.freshness} />
        </article>
      ))}
    </div>
  );
}
