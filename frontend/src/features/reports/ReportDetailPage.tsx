import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type {
  AnalysisStreamEvent,
  ReportStatus,
} from "../../domain/report";
import { EvidenceList } from "./EvidenceList";
import { RiskFlags } from "./RiskFlags";

const statusLabels: Record<ReportStatus, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  degraded: "已降级",
  failed: "失败",
};

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

export function ReportDetailPage() {
  const api = useWorkbenchApi();
  const { reportId } = useParams();
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const [retryEvent, setRetryEvent] =
    useState<AnalysisStreamEvent | null>(null);
  const reportQuery = useQuery({
    queryKey: ["report", reportId],
    enabled: reportId !== undefined,
    queryFn: () => {
      if (reportId === undefined) {
        throw new Error("Report ID is required");
      }
      return api.getReport(reportId);
    },
  });
  const retryMutation = useMutation({
    mutationKey: ["retry-report", reportQuery.data?.id],
    mutationFn: () => {
      const report = reportQuery.data;
      if (report === undefined) {
        throw new Error("Report is not available");
      }
      return api.retryReport(report.id);
    },
    onSuccess: ({ analysisId }) => {
      unsubscribeRef.current?.();
      setRetryEvent(null);
      unsubscribeRef.current = api.subscribeReport(
        analysisId,
        setRetryEvent,
      );
    },
  });

  useEffect(
    () => () => {
      unsubscribeRef.current?.();
    },
    [],
  );

  if (reportId === undefined) {
    return (
      <PageState state="unavailable" message="报告 ID 缺失，无法读取详情。" />
    );
  }

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
  const retryAnalysisId = retryMutation.data?.analysisId;
  const journalSearch = new URLSearchParams({
    linkedAnalysisReportId: report.id,
  }).toString();

  return (
    <article className="research-page report-detail">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">
            {report.symbol} · {statusLabels[report.status]}
          </p>
          <h1>报告详情</h1>
          <h2 className="report-detail__title">{report.title}</h2>
          <p>{report.summary}</p>
        </div>
      </header>

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
              <time dateTime={report.dataCutoffAt}>
                {report.dataCutoffAt}
              </time>
            </dd>
          </div>
        </dl>
      </section>

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
      <EvidenceList evidence={report.evidence} />

      <section
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
              retryMutation.mutate();
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
        {retryAnalysisId !== undefined ? (
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
      </section>
    </article>
  );
}
