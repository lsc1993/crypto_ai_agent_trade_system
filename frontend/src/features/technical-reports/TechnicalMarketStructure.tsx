import type { TechnicalReport } from "../../domain/technical-report";
import { priceLabel } from "./technical-copy";
import { periodLabels, trendLabels, volumeLabels } from "./technical-presentation";

export function TechnicalMarketStructure({report}: {report: TechnicalReport}) {
  const facts = report.analysis.facts;
  if (facts === null) return <p>数据不足，未计算技术事实。</p>;
  const trends = ["1d", "4h", "1h"].map((period) => facts.trendAlignment[period]);
  const complete = trends.every((trend) => trend !== undefined);
  const aligned = complete && new Set(trends).size === 1;
  const trendStatus = !complete ? "周期数据不完整" : aligned && trends[0] === "neutral" ? "多周期均为中性，未形成方向共识" : aligned ? "多周期方向一致" : "多周期方向存在冲突";
  return <>
    <p className="technical-structure-status">{trendStatus} · {facts.breakout === "none" ? "尚未确认收盘突破" : facts.breakout === "long" ? "冻结行情已向上突破" : "冻结行情已向下突破"}</p>
    <div className="technical-table-scroll"><table className="technical-period-table" aria-label="多周期趋势对照">
      <thead><tr><th scope="col">周期</th><th scope="col">趋势</th><th scope="col">20根简单均线</th><th scope="col">50根简单均线</th></tr></thead>
      <tbody>{["1d", "4h", "1h"].map((period) => <tr key={period}><th scope="row">{periodLabels[period]}</th><td><span className="technical-trend" data-trend={facts.trendAlignment[period]}>{trendLabels[facts.trendAlignment[period] ?? ""] ?? "缺失"}</span></td><td>{facts.sma20[period] === undefined ? "缺失" : priceLabel(facts.sma20[period])}</td><td>{facts.sma50[period] === undefined ? "缺失" : priceLabel(facts.sma50[period])}</td></tr>)}</tbody>
    </table></div>
    <dl className="technical-facts">
      <div><dt>1小时区间高 / 低（USDT）</dt><dd>{priceLabel(facts.rangeHigh)} / {priceLabel(facts.rangeLow)}</dd></div>
      <div><dt>相对成交量 · 20根基准</dt><dd>{facts.volumeRatio} 倍 · {volumeLabels[facts.volumeSignal]}</dd></div>
      <div><dt>平均真实波幅 · 14根（USDT）</dt><dd>{priceLabel(facts.atr14)}</dd></div>
      <div><dt>1小时形态观察</dt><dd>{[facts.smallBody && "小实体", facts.longUpperWick && "长上影", facts.longLowerWick && "长下影"].filter(Boolean).join(" · ") || "未识别指定形态"}</dd></div>
    </dl>
    <p className="technical-caption">均线与价格单位为 USDT；所有判断对应冻结数据，不代表当前实时状态。</p>
  </>;
}
