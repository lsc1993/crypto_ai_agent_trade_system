import Decimal from "decimal.js";

import type { FactorAnalysis, FactorFact, FactorTopic } from "../../domain/report-factors";
import { formatDecimal, formatFundingRate } from "../../shared/format";

const statuses = {
  available: "数据可用", partial: "部分覆盖", missing: "缺少数据", failed: "采集失败",
} as const;
const outlooks = { bullish: "偏利多", bearish: "偏利空", neutral: "影响中性／有分歧" } as const;
const topics = [
  ["policy", "近一周美国关键政策", "政策与流动性"],
  ["funding", "资金费率影响", "衍生品持仓成本"],
  ["etf", "美国现货 ETF 资金流向", "现货资金需求"],
] as const;

export function ReportFactorAnalysis({ analysis }: { analysis?: FactorAnalysis | null }) {
  if (!analysis) return null;
  return <>
    {topics.map(([kind, title, subtitle]) => <FactorSection key={kind} kind={kind}
      title={title} subtitle={subtitle} topic={analysis[kind]} />)}
  </>;
}

function FactorSection({ kind, title, subtitle, topic }: {
  kind: string; title: string; subtitle: string; topic: FactorTopic;
}) {
  const interpretation = topic.interpretation;
  return <section className="research-report__section research-report__factor"
    aria-labelledby={`factor-${kind}-title`}>
    <div className="research-report__factor-heading">
      <div><p className="research-report__section-kicker">{subtitle}</p>
        <h2 id={`factor-${kind}-title`}>{title}</h2></div>
      <span className={`research-report__factor-status research-report__factor-status--${topic.status}`}>
        {statuses[topic.status]}
      </span>
    </div>
    <div className="research-report__factor-times">
      {topic.windowStart ? <p>研究窗口（UTC）：{topic.windowStart} 至 {topic.windowEnd}</p> : null}
      {topic.observedAt ? <p>最新观测（UTC）：<time dateTime={topic.observedAt}>{topic.observedAt}</time></p> : null}
      {topic.fetchedAt ? <p>数据抓取（UTC）：<time dateTime={topic.fetchedAt}>{topic.fetchedAt}</time></p> : null}
    </div>
    {topic.facts.length > 0 ? <dl className="research-report__factor-facts">
      {topic.facts.map((fact) => <div key={fact.label}>
        <dt>{fact.label}</dt><dd>{formatFact(fact)}</dd>
      </div>)}
    </dl> : null}
    {topic.events.length > 0 ? <ul className="research-report__card-list">
      {topic.events.map((event) => <li key={event.evidenceId}>
        <strong>{event.institution}</strong>
        <h3><a href={event.sourceUrl} target="_blank" rel="noreferrer">{event.title}</a></h3>
        <p>发布时间（UTC）：<time dateTime={event.publishedAt}>{event.publishedAt}</time></p>
        <p>{event.summary}</p>
      </li>)}
    </ul> : null}
    {interpretation ? <div className="research-report__factor-interpretation">
      <h3>行情影响 · {outlooks[interpretation.outlook]}</h3>
      <p>{interpretation.summary}</p>
      <div className="research-report__detail-grid">
        <div><h4>短期影响</h4><p>{interpretation.shortTerm}</p></div>
        <div><h4>长期影响</h4><p>{interpretation.longTerm}</p></div>
      </div>
      <p><strong>失效与复核条件：</strong>{interpretation.invalidation}</p>
    </div> : <p className="research-report__annotation">本专题暂无经过验证的模型解释。</p>}
    {topic.evidenceIds.length > 0 ? <p className="research-report__evidence-links">
      {topic.evidenceIds.map((id, index) => <a key={id} href={`#evidence-${id}`}>
        查看证据 {index + 1}
      </a>)}
    </p> : null}
    {topic.limitations.length > 0 ? <ul className="research-report__factor-limits">
      {topic.limitations.map((limit) => <li key={limit}>{limit}</li>)}
    </ul> : null}
  </section>;
}

function formatFact(fact: FactorFact): string {
  if (fact.value === null) return "未披露／不可用";
  if (fact.unit === "text") return fact.value;
  const value = new Decimal(fact.value).toFixed();
  if (fact.unit === "rate") return formatFundingRate(value);
  if (fact.unit === "usd") return `${formatDecimal(value, { showPositiveSign: true })} USD`;
  return formatDecimal(value);
}
