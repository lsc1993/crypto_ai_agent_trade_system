import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type { ReportStatus } from "../../domain/report";
import { ReportGenerator } from "./ReportGenerator";

const statusLabels: Record<ReportStatus, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  degraded: "已降级",
  failed: "失败",
};

export function ReportListPage() {
  const api = useWorkbenchApi();
  const reportsQuery = useQuery({
    queryKey: ["reports", { page: 1, pageSize: 20 }],
    queryFn: () => api.listReports({ page: 1, pageSize: 20 }),
  });

  if (reportsQuery.isPending) {
    return <PageState state="loading" />;
  }

  if (reportsQuery.isError) {
    return (
      <PageState
        state="error"
        message="无法读取分析报告，请稍后重试。"
      />
    );
  }

  return (
    <section className="research-page reports-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">可审计研究记录</p>
          <h1>分析报告</h1>
          <p>
            报告区分事实、推断、风险与限制，表达观察和不确定性，不构成交易指令。
          </p>
        </div>
      </header>

      <ReportGenerator symbol="BTCUSDT" />

      <section
        className="reports-page__history"
        aria-labelledby="reports-history-title"
      >
        <div className="section-heading">
          <div>
            <p className="section-kicker">REPORT HISTORY</p>
            <h2 id="reports-history-title">历史报告</h2>
          </div>
        </div>
        {reportsQuery.data.items.length === 0 ? (
          <PageState state="empty" message="暂无历史研究报告。" />
        ) : (
          <div className="report-card-list">
            {reportsQuery.data.items.map((report) => (
              <article
                className="report-card"
                aria-label={report.title}
                key={report.id}
              >
                <header className="report-card__header">
                  <div>
                    <p className="section-kicker">{report.symbol}</p>
                    <h3>{report.title}</h3>
                  </div>
                  <span
                    className={`report-status report-status--${report.status}`}
                  >
                    {statusLabels[report.status]}
                  </span>
                </header>
                <p>{report.summary}</p>
                <dl className="metadata-list">
                  <div>
                    <dt>分析 ID</dt>
                    <dd>{report.analysisId}</dd>
                  </div>
                  <div>
                    <dt>报告创建时间（UTC）</dt>
                    <dd>
                      <time dateTime={report.createdAt}>
                        {report.createdAt}
                      </time>
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
                <Link className="text-link" to={`/reports/${report.id}`}>
                  查看研究报告
                </Link>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
