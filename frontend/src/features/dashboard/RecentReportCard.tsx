import { Link } from "react-router-dom";

import type { AnalysisReportSummary } from "../../domain/report";

const reportStatusLabels: Record<
  AnalysisReportSummary["status"],
  string
> = {
  queued: "等待中",
  running: "研究生成中",
  completed: "已完成",
  degraded: "降级完成",
  failed: "生成失败",
};

export interface RecentReportCardProps {
  report: AnalysisReportSummary;
}

export function RecentReportCard({ report }: RecentReportCardProps) {
  return (
    <article className="report-card">
      <header className="report-card__header">
        <div>
          <p className="section-kicker">{report.symbol} · AI 研究</p>
          <h3>{report.title}</h3>
        </div>
        <span className={`report-status report-status--${report.status}`}>
          {reportStatusLabels[report.status]}
        </span>
      </header>
      <p>{report.summary}</p>
      <dl className="metadata-list">
        <div>
          <dt>创建时间</dt>
          <dd>
            <time dateTime={report.createdAt}>{report.createdAt}</time>
          </dd>
        </div>
        <div>
          <dt>数据截止时间</dt>
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
      <Link className="text-link" to={`/reports/${report.id}`}>
        查看研究报告
      </Link>
    </article>
  );
}
