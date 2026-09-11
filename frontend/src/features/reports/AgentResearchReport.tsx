import type { AnalysisReport } from "../../domain/report";
import {
  formatDailyChange,
  formatFundingRate,
  formatMarketPrice,
  formatMarketVolume,
  formatOpenInterest,
} from "../../shared/format";
import "./research-report.css";
import { ReportFactorAnalysis } from "./ReportFactorAnalysis";

type DualHorizonAnalysis = Extract<
  NonNullable<AnalysisReport["agentAnalysis"]>,
  { horizon: "dual_horizon" }
>;

type DegradedAgentAnalysis = Extract<
  NonNullable<AnalysisReport["agentAnalysis"]>,
  { horizon: "1_to_3_days" }
>;

type MarketStructureAnalysis = Pick<
  NonNullable<AnalysisReport["agentAnalysis"]>,
  "supportZones" | "resistanceZones"
>;

export type DualHorizonReport = Omit<AnalysisReport, "agentAnalysis"> & {
  agentAnalysis: DualHorizonAnalysis;
};

export type DegradedAgentReport = Omit<AnalysisReport, "agentAnalysis"> & {
  agentAnalysis: DegradedAgentAnalysis;
};

const outlookLabels = {
  bullish: "偏强",
  bearish: "偏弱",
  neutral: "中性",
} as const;

const confidenceLabels = {
  low: "较低",
  medium: "中等",
  high: "较高",
} as const;

const freshnessLabels = {
  fresh: "新鲜",
  stale: "过期",
  missing: "缺失",
  failed: "采集失败",
} as const;

const coverageLabels = {
  none: "无覆盖",
  partial: "部分覆盖",
  complete: "完整",
} as const;

const validationCategoryLabels = {
  chinese_text_required: "中文文本要求",
  narrative_length: "正文长度",
  schema: "字段结构",
  text_empty: "必填文本",
  text_length: "单项文本长度",
  trading_instruction: "交易指令限制",
} as const;

const statusLabels = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  degraded: "已降级",
  failed: "失败",
} as const;

export function AgentResearchReport({ report }: { report: DualHorizonReport }) {
  const analysis = report.agentAnalysis;
  const narrative = analysis.narrative;
  const metrics = marketMetricCards(analysis);

  return (
    <article className="research-report" aria-label="双周期市场研究报告">
      <header className="research-report__hero">
        <p className="research-report__eyebrow">
          {report.symbol} · {statusLabels[report.status]} · 冻结公开证据研究
        </p>
        <h1>{narrative.marketOverview.headline}</h1>
        <p className="research-report__summary">
          {narrative.marketOverview.summary}
        </p>
        <EvidenceReferences evidenceIds={narrative.marketOverview.evidenceIds} />
        <dl className="research-report__hero-meta">
          <div>
            <dt>数据截止时间（UTC）</dt>
            <dd>
              {report.dataCutoffAt === null ? (
                "无可用数据"
              ) : (
                <time dateTime={report.dataCutoffAt}>
                  {report.dataCutoffAt}
                </time>
              )}
            </dd>
          </div>
          <div>
            <dt>来源覆盖</dt>
            <dd>来源覆盖：{coverageLabels[analysis.dataQuality.sourceCoverage]}</dd>
          </div>
          <div>
            <dt>模型置信度</dt>
            <dd>模型置信度：{confidenceLabels[analysis.confidence]}</dd>
          </div>
          <div>
            <dt>数据新鲜度</dt>
            <dd>{freshnessLabels[analysis.dataQuality.freshness]}</dd>
          </div>
        </dl>
      </header>

      <section
        className="research-report__metrics"
        aria-labelledby="research-report-metrics-title"
      >
        <div className="research-report__section-heading">
          <p>市场快照</p>
          <h2 id="research-report-metrics-title">关键指标</h2>
        </div>
        <div className="research-report__metric-grid">
          {metrics.map((metric) => (
            <article className="research-report__metric-card" key={metric.label}>
              <h3>{metric.label}</h3>
              <p>{metric.value}</p>
              <span>{metric.annotation}</span>
            </article>
          ))}
        </div>
      </section>

      <section
        className="research-report__section research-report__section--overview"
        aria-labelledby="research-report-overview-title"
      >
        <p className="research-report__section-kicker">冻结证据综述</p>
        <h2 id="research-report-overview-title">市场概况</h2>
        <p>{narrative.marketOverview.summary}</p>
        <EvidenceReferences evidenceIds={narrative.marketOverview.evidenceIds} />
      </section>

      <ReportFactorAnalysis analysis={analysis.factorAnalysis ?? null} />

      <PerspectiveSection
        analysis={analysis}
        horizonLabel="数天至两周"
        perspective={narrative.shortTerm}
        title="短期市场观点"
        includeZones
      />
      <PerspectiveSection
        analysis={analysis}
        horizonLabel="数周至数月"
        perspective={narrative.longTerm}
        title="长期市场观点"
      />

      <section
        className="research-report__section research-report__section--catalyst"
        aria-labelledby="research-report-catalysts-title"
      >
        <p className="research-report__section-kicker">需要跟踪的公开信息</p>
        <h2 id="research-report-catalysts-title">潜在催化事件</h2>
        {analysis.catalysts.length === 0 ? (
          <p>冻结证据中未识别可归因的潜在催化事件。</p>
        ) : (
          <ul className="research-report__card-list">
            {analysis.catalysts.map((catalyst) => (
              <li key={`${catalyst.category}-${catalyst.claim}`}>
                <h3>{catalyst.category}</h3>
                <p>{catalyst.claim}</p>
                <p className="research-report__annotation">
                  方向：{outlookLabels[catalyst.direction]} · 观察节点：
                  {catalyst.timing}
                </p>
                <EvidenceReferences evidenceIds={catalyst.evidenceIds} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        className="research-report__section research-report__section--risk"
        aria-labelledby="research-report-risks-title"
      >
        <p className="research-report__section-kicker">条件改变时应重新评估</p>
        <h2 id="research-report-risks-title">风险与失效条件</h2>
        <RiskList risks={analysis.risksAndInvalidation} />
        {analysis.dataQuality.missingInputs.length === 0 ? null : (
          <p className="research-report__annotation">
            缺失输入：{analysis.dataQuality.missingInputs.join("、")}
          </p>
        )}
        {analysis.limitations.length === 0 ? null : (
          <p className="research-report__annotation">
            限制：{analysis.limitations.join("、")}
          </p>
        )}
      </section>
    </article>
  );
}

export function DegradedAgentResearchReport({
  report,
}: {
  report: DegradedAgentReport;
}) {
  const analysis = report.agentAnalysis;
  const trends = Object.entries(analysis.trendAlignment);

  return (
    <article
      className="research-report research-report--degraded"
      aria-label="Agent 降级研究报告"
    >
      <header className="research-report__hero">
        <p className="research-report__eyebrow">
          {report.symbol} · {statusLabels[report.status]} · 冻结公开证据研究
        </p>
        <h1>本次 AI 详尽报告未生成</h1>
        <p className="research-report__summary">
          模型输出未通过格式校验，因此系统没有将其展示为市场观点。以下保留可审计的专题事实、冻结市场结构与数据质量信息；请以新的研究任务重新生成双周期中文报告。
        </p>
        <dl className="research-report__hero-meta">
          <div>
            <dt>模型输出</dt>
            <dd>未通过格式校验</dd>
          </div>
          {report.validationFailure === undefined || report.validationFailure === null ? null : (
            <div>
              <dt>格式校验摘要</dt>
              <dd>
                已尝试 {report.validationFailure.attemptCount} 次 · 发现 {report.validationFailure.issueCount} 项问题
                {report.validationFailure.fieldPaths.length === 0 ? "" : ` · 字段：${report.validationFailure.fieldPaths.join("、")}`}
                {report.validationFailure.errorCategories.length === 0 ? "" : ` · 类别：${report.validationFailure.errorCategories.map((category) => validationCategoryLabels[category]).join("、")}`}
              </dd>
            </div>
          )}
          <div>
            <dt>数据截止时间（UTC）</dt>
            <dd>
              {report.dataCutoffAt === null ? (
                "无可用数据"
              ) : (
                <time dateTime={report.dataCutoffAt}>
                  {report.dataCutoffAt}
                </time>
              )}
            </dd>
          </div>
          <div>
            <dt>来源覆盖</dt>
            <dd>{coverageLabels[analysis.dataQuality.sourceCoverage]}</dd>
          </div>
          <div>
            <dt>数据新鲜度</dt>
            <dd>{freshnessLabels[analysis.dataQuality.freshness]}</dd>
          </div>
        </dl>
      </header>

      <ReportFactorAnalysis analysis={analysis.factorAnalysis ?? null} />

      <section
        className="research-report__section research-report__section--overview"
        aria-labelledby="degraded-report-structure-title"
      >
        <p className="research-report__section-kicker">仅保留确定性市场输入</p>
        <h2 id="degraded-report-structure-title">已冻结的市场结构</h2>
        {trends.length === 0 ? (
          <p>本次未形成可用的周期趋势输入。</p>
        ) : (
          <p>
            周期趋势：{trends.map(([timeframe, direction]) => `${timeframe} ${direction}`).join(" · ")}
          </p>
        )}
        <ZoneList analysis={analysis} />
      </section>

      <section
        className="research-report__section research-report__section--risk"
        aria-labelledby="degraded-report-limitations-title"
      >
        <p className="research-report__section-kicker">重新生成前需要注意</p>
        <h2 id="degraded-report-limitations-title">数据限制与重试提示</h2>
        {analysis.dataQuality.missingInputs.length === 0 ? (
          <p>未记录缺失输入。</p>
        ) : (
          <p>缺失输入：{analysis.dataQuality.missingInputs.join("、")}</p>
        )}
        {analysis.limitations.length === 0 ? null : (
          <p className="research-report__annotation">
            限制：{analysis.limitations.join("、")}
          </p>
        )}
      </section>
    </article>
  );
}

function marketMetricCards(analysis: DualHorizonAnalysis) {
  const metrics = analysis.marketMetrics;
  const hasSentiment = metrics.fearGreedValue !== null;
  return [
    {
      label: "价格",
      value: formatMarketPrice(metrics.price),
      annotation: "本次冻结公开市场数据",
    },
    {
      label: "24 小时变化",
      value: formatDailyChange(metrics.change24h),
      annotation: "本次冻结公开市场数据",
    },
    {
      label: "24 小时成交额",
      value: formatMarketVolume(metrics.volume24h),
      annotation: "本次冻结公开市场数据",
    },
    {
      label: "情绪",
      value: hasSentiment
        ? `${metrics.fearGreedValue} · ${metrics.fearGreedClassification}`
        : "本次未取得",
      annotation: hasSentiment
        ? `7 日变化 ${formatSignedInteger(metrics.fearGreedChange7d)}`
        : "公开情绪数据未取得",
    },
    {
      label: "资金费率",
      value: formatFundingRate(metrics.fundingRate),
      annotation: "本次冻结公开市场数据",
    },
    {
      label: "未平仓量",
      value: formatOpenInterest(metrics.openInterest),
      annotation: "本次冻结公开市场数据",
    },
  ];
}

function formatSignedInteger(value: number | null): string {
  if (value === null) {
    return "本次未取得";
  }
  return value > 0 ? `+${value}` : String(value);
}

function PerspectiveSection({
  analysis,
  horizonLabel,
  perspective,
  title,
  includeZones = false,
}: {
  analysis: DualHorizonAnalysis;
  horizonLabel: string;
  perspective: DualHorizonAnalysis["narrative"]["shortTerm"];
  title: string;
  includeZones?: boolean;
}) {
  const sectionId =
    perspective.horizon === "short_term"
      ? "research-report-short-term-title"
      : "research-report-long-term-title";

  return (
    <section
      className="research-report__section research-report__section--perspective"
      aria-labelledby={sectionId}
    >
      <p className="research-report__section-kicker">
        {horizonLabel} · {outlookLabels[perspective.outlook]}
      </p>
      <h2 id={sectionId}>{title}</h2>
      <h3>{perspective.heading}</h3>
      <p>{perspective.thesis}</p>
      <div className="research-report__detail-grid">
        <section aria-label={`${title}的驱动因素`}>
          <h3>主要驱动因素</h3>
          <ul className="research-report__card-list">
            {perspective.drivers.map((driver) => (
              <li key={`${driver.label}-${driver.detail}`}>
                <h4>{driver.label}</h4>
                <p>{driver.detail}</p>
                <EvidenceReferences evidenceIds={driver.evidenceIds} />
              </li>
            ))}
          </ul>
        </section>
        <section aria-label={`${title}的失效条件`}>
          <h3>失效条件</h3>
          <RiskList risks={perspective.invalidation} />
        </section>
      </div>
      {includeZones ? <ZoneList analysis={analysis} /> : null}
    </section>
  );
}

function ZoneList({ analysis }: { analysis: MarketStructureAnalysis }) {
  return (
    <section className="research-report__zones" aria-label="关键支撑与阻力">
      <h3>关键支撑与阻力</h3>
      <div className="research-report__detail-grid">
        <ZoneColumn title="支撑区域" zones={analysis.supportZones} />
        <ZoneColumn title="阻力区域" zones={analysis.resistanceZones} />
      </div>
    </section>
  );
}

function ZoneColumn({
  title,
  zones,
}: {
  title: string;
  zones: MarketStructureAnalysis["supportZones"];
}) {
  return (
    <section aria-label={title}>
      <h4>{title}</h4>
      {zones.length === 0 ? (
        <p>未识别证据化价位区间。</p>
      ) : (
        <ul className="research-report__zone-list">
          {zones.map((zone) => (
            <li key={`${zone.timeframe}-${zone.lower}-${zone.upper}`}>
              <strong>
                {zone.lower} – {zone.upper}
              </strong>
              <span>{zone.timeframe}</span>
              <p>{zone.rationale}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RiskList({
  risks,
}: {
  risks: DualHorizonAnalysis["risksAndInvalidation"];
}) {
  if (risks.length === 0) {
    return <p>未记录额外的证据化失效条件。</p>;
  }

  return (
    <ul className="research-report__card-list">
      {risks.map((risk) => (
        <li key={`${risk.condition}-${risk.impact}`}>
          <h4>{risk.condition}</h4>
          <p>{risk.impact}</p>
          <EvidenceReferences evidenceIds={risk.evidenceIds} />
        </li>
      ))}
    </ul>
  );
}

function EvidenceReferences({ evidenceIds }: { evidenceIds: string[] }) {
  return (
    <p className="research-report__evidence-links">
      {evidenceIds.map((evidenceId) => (
        <a href={`#evidence-${evidenceId}`} key={evidenceId}>
          查看证据 {evidenceId}
        </a>
      ))}
    </p>
  );
}
