import { useMutation, useQuery } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type {
  AnalysisReport,
  AnalysisStreamEvent,
  ReportStatus,
} from "../../domain/report";
import {
  AgentResearchReport,
  type DualHorizonReport,
} from "./AgentResearchReport";
import { EvidenceList } from "./EvidenceList";
import { RiskFlags } from "./RiskFlags";

const statusLabels: Record<ReportStatus, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  degraded: "已降级",
  failed: "失败",
};

function isTerminalStatus(status: ReportStatus): boolean {
  return (
    status === "completed" ||
    status === "degraded" ||
    status === "failed"
  );
}

function isDualHorizonReport(
  report: AnalysisReport,
): report is DualHorizonReport {
  return report.agentAnalysis?.horizon === "dual_horizon";
}

function ObservationSection({
  id,
  title,
  items,
  emptyMessage,
  variant,
}: {
  id: string;
  title: string;
  items: string[];
  emptyMessage: string;
  variant: "fact" | "inference";
}) {
  return (
    <section
      className={`report-section report-section--${variant}`}
      aria-labelledby={id}
    >
      <h2 id={id}>{title}</h2>
      {items.length === 0 ? (
        <p>{emptyMessage}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AgentResearchPanels({ report }: { report: AnalysisReport }) {
  const analysis = report.agentAnalysis;
  if (analysis === null) {
    return null;
  }

  return (
    <div className="report-agent-research">
      <section
        className="report-section report-section--inference"
        aria-labelledby="agent-outlook-title"
      >
        <h2 id="agent-outlook-title">未来 1–3 天市场研判</h2>
        <dl className="metadata-list">
          <div>
            <dt>方向</dt>
            <dd>{analysis.outlook}</dd>
          </div>
          <div>
            <dt>置信度</dt>
            <dd>{analysis.confidence}</dd>
          </div>
          <div>
            <dt>数据新鲜度</dt>
            <dd>{analysis.dataQuality.freshness}</dd>
          </div>
          <div>
            <dt>来源覆盖</dt>
            <dd>{analysis.dataQuality.sourceCoverage}</dd>
          </div>
        </dl>
        {Object.keys(analysis.trendAlignment).length === 0 ? null : (
          <p>
            周期趋势：{" "}
            {Object.entries(analysis.trendAlignment)
              .map(([timeframe, direction]) => `${timeframe} ${direction}`)
              .join(" · ")}
          </p>
        )}
      </section>

      <section
        className="report-section report-section--fact"
        aria-labelledby="agent-structure-title"
      >
        <h2 id="agent-structure-title">关键支撑与阻力</h2>
        <ZoneList title="支撑" zones={analysis.supportZones} />
        <ZoneList title="阻力" zones={analysis.resistanceZones} />
      </section>

      <section
        className="report-section report-section--inference"
        aria-labelledby="agent-catalysts-title"
      >
        <h2 id="agent-catalysts-title">潜在催化事件</h2>
        {analysis.catalysts.length === 0 ? (
          <p>冻结证据中未识别可归因的近期催化事件。</p>
        ) : (
          <ul>
            {analysis.catalysts.map((catalyst) => (
              <li key={`${catalyst.category}-${catalyst.claim}`}>
                <p>{catalyst.claim}</p>
                <p>
                  {catalyst.category} · {catalyst.direction} · {catalyst.timing}
                </p>
                <EvidenceReferences evidenceIds={catalyst.evidenceIds} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        className="report-section report-section--risk"
        aria-labelledby="agent-risks-title"
      >
        <h2 id="agent-risks-title">风险与失效条件</h2>
        {analysis.risksAndInvalidation.length === 0 ? (
          <p>未记录额外的证据化失效条件。</p>
        ) : (
          <ul>
            {analysis.risksAndInvalidation.map((risk) => (
              <li key={`${risk.condition}-${risk.impact}`}>
                <p>{risk.condition}</p>
                <p>{risk.impact}</p>
                <EvidenceReferences evidenceIds={risk.evidenceIds} />
              </li>
            ))}
          </ul>
        )}
        {analysis.dataQuality.missingInputs.length === 0 ? null : (
          <p>缺失输入：{analysis.dataQuality.missingInputs.join("、")}</p>
        )}
        {analysis.limitations.length === 0 ? null : (
          <p>限制：{analysis.limitations.join("、")}</p>
        )}
      </section>
    </div>
  );
}

function ZoneList({
  title,
  zones,
}: {
  title: string;
  zones: NonNullable<AnalysisReport["agentAnalysis"]>["supportZones"];
}) {
  return (
    <div>
      <h3>{title}</h3>
      {zones.length === 0 ? (
        <p>未识别证据化价位区间。</p>
      ) : (
        <ul>
          {zones.map((zone) => (
            <li key={`${zone.timeframe}-${zone.lower}-${zone.upper}`}>
              {zone.timeframe} · {zone.lower} – {zone.upper} · {zone.rationale}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EvidenceReferences({ evidenceIds }: { evidenceIds: string[] }) {
  return (
    <p>
      {evidenceIds.map((evidenceId) => (
        <a href={`#evidence-${evidenceId}`} key={evidenceId}>
          查看证据 {evidenceId}
        </a>
      ))}
    </p>
  );
}

export function ReportDetailPage() {
  const { reportId } = useParams();

  if (reportId === undefined) {
    return (
      <PageState state="unavailable" message="报告 ID 缺失，无法读取详情。" />
    );
  }

  return <ReportDetailContent key={reportId} reportId={reportId} />;
}

function ReportDetailContent({ reportId }: { reportId: string }) {
  const api = useWorkbenchApi();
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const activeAnalysisIdRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  const requestEpochRef = useRef(0);
  const [retryEvent, setRetryEvent] =
    useState<AnalysisStreamEvent | null>(null);
  const [retryAnalysisId, setRetryAnalysisId] = useState<string | null>(
    null,
  );
  const clearRetrySubscription = useCallback(() => {
    const unsubscribe = unsubscribeRef.current;
    unsubscribeRef.current = null;
    activeAnalysisIdRef.current = null;
    unsubscribe?.();
  }, []);
  const reportQuery = useQuery({
    queryKey: ["report", reportId],
    queryFn: () => api.getReport(reportId),
  });
  const retryMutation = useMutation({
    mutationKey: ["retry-report", reportQuery.data?.id],
    mutationFn: ({
      targetReportId,
    }: {
      targetReportId: string;
      requestEpoch: number;
    }) => api.retryReport(targetReportId),
    onSuccess: (
      { analysisId },
      { targetReportId, requestEpoch },
    ) => {
      if (
        !mountedRef.current ||
        requestEpochRef.current !== requestEpoch ||
        reportId !== targetReportId
      ) {
        return;
      }
      clearRetrySubscription();
      setRetryAnalysisId(analysisId);
      setRetryEvent(null);
      activeAnalysisIdRef.current = analysisId;
      const unsubscribe = api.subscribeReport(
        analysisId,
        (nextEvent) => {
          if (activeAnalysisIdRef.current !== analysisId) {
            return;
          }
          setRetryEvent(nextEvent);
          if (isTerminalStatus(nextEvent.status)) {
            clearRetrySubscription();
          }
        },
      );
      if (
        reportId === targetReportId &&
        activeAnalysisIdRef.current === analysisId
      ) {
        unsubscribeRef.current = unsubscribe;
      } else {
        unsubscribe();
      }
    },
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestEpochRef.current += 1;
      clearRetrySubscription();
    };
  }, [clearRetrySubscription]);

  if (reportQuery.isPending) {
    return <PageState state="loading" />;
  }

  if (reportQuery.isError) {
    return (
      <PageState
        state="error"
        message="无法读取报告详情，请稍后重试。"
      />
    );
  }

  const report = reportQuery.data;
  const journalSearch = new URLSearchParams({
    linkedAnalysisReportId: report.id,
  }).toString();
  const isAgentReport = report.generatorKind === "langgraph_deepseek";
  const isDualHorizonAgentReport = isDualHorizonReport(report);

  return (
    <article className="research-page report-detail">
      {isDualHorizonAgentReport ? null : (
        <header className="research-page__heading">
          <div>
            <p className="route-page__kicker">
              {report.symbol} · {statusLabels[report.status]}
            </p>
            <h1>报告详情</h1>
            {isAgentReport ? null : (
              <>
                <h2 className="report-detail__title">{report.title}</h2>
                <p>{report.summary}</p>
              </>
            )}
          </div>
        </header>
      )}

      <section
        className="report-audit-panel"
        aria-labelledby="report-audit-title"
      >
        <h2 id="report-audit-title">报告审计信息</h2>
        <dl className="metadata-list">
          <div>
            <dt>报告 ID</dt>
            <dd>{report.id}</dd>
          </div>
          <div>
            <dt>历史分析 ID</dt>
            <dd>{report.analysisId}</dd>
          </div>
          <div>
            <dt>报告创建时间（UTC）</dt>
            <dd>
              <time dateTime={report.createdAt}>{report.createdAt}</time>
            </dd>
          </div>
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
        </dl>
      </section>

      {isDualHorizonAgentReport ? (
        <AgentResearchReport report={report} />
      ) : isAgentReport ? (
        <AgentResearchPanels report={report} />
      ) : (
        <>
          <div className="report-observation-grid">
            <ObservationSection
              id="report-facts-title"
              title="事实观察"
              items={report.facts}
              emptyMessage="未记录事实观察。"
              variant="fact"
            />
            <ObservationSection
              id="report-inferences-title"
              title="分析推断"
              items={report.inferences}
              emptyMessage="未形成分析推断。"
              variant="inference"
            />
          </div>
          <RiskFlags
            risks={report.risks}
            limitations={report.limitations}
          />
        </>
      )}
      <EvidenceList evidence={report.evidence} />

      {isAgentReport ? null : <section
        className="report-actions"
        aria-labelledby="report-actions-title"
      >
        <div>
          <h2 id="report-actions-title">后续记录</h2>
          <p>
            可创建仅关联此报告 ID 的模拟交易日志；不会复制报告正文、证据，也不会生成交易推荐。
          </p>
        </div>
        <div className="report-actions__controls">
          <Link
            className="primary-link"
            to={`/trades/new?${journalSearch}`}
          >
            基于此分析创建交易日志
          </Link>
          <button
            className="secondary-action"
            type="button"
            disabled={retryMutation.isPending}
            onClick={() => {
              requestEpochRef.current += 1;
              retryMutation.mutate({
                targetReportId: report.id,
                requestEpoch: requestEpochRef.current,
              });
            }}
          >
            以新分析任务重试
          </button>
        </div>
        {retryMutation.isPending ? (
          <p role="status">正在创建新的分析任务。</p>
        ) : null}
        {retryMutation.isError ? (
          <p className="inline-error" role="alert">
            重试任务创建失败，请稍后再试。
          </p>
        ) : null}
        {retryAnalysisId !== null ? (
          <div className="report-retry-status">
            <p>新的分析 ID</p>
            <strong>{retryAnalysisId}</strong>
            {retryEvent !== null ? (
              <p role="status">
                {statusLabels[retryEvent.status]} ·{" "}
                <time dateTime={retryEvent.occurredAt}>
                  {retryEvent.occurredAt}
                </time>
              </p>
            ) : (
              <p>等待生命周期事件。</p>
            )}
          </div>
        ) : null}
      </section>}
    </article>
  );
}
