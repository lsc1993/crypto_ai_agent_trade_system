import { DataFreshnessBadge } from "../../components/common/DataFreshnessBadge";
import type { MarketSummary } from "../../domain/market";
import {
  formatFundingRate,
  formatOpenInterest,
} from "../../shared/format";

export interface DerivativePanelProps {
  summary: MarketSummary;
}

export function DerivativePanel({ summary }: DerivativePanelProps) {
  return (
    <section
      className="research-panel derivative-panel"
      aria-labelledby="derivative-panel-title"
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">DERIVATIVES</p>
          <h2 id="derivative-panel-title">衍生品指标</h2>
        </div>
      </div>
      <dl className="metric-list metric-list--compact">
        <div>
          <dt>资金费率</dt>
          <dd>{formatFundingRate(summary.fundingRate)}</dd>
        </div>
        <div>
          <dt>未平仓量</dt>
          <dd>{formatOpenInterest(summary.openInterest)}</dd>
        </div>
      </dl>
      <DataFreshnessBadge {...summary.freshness} />
    </section>
  );
}
