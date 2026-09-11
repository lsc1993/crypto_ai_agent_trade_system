import { useQuery } from "@tanstack/react-query";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import { WorkbenchHttpError } from "../../shared/api/http-transport";
import { ResearchSymbolSelect } from "../research-symbols/ResearchSymbolSelect";
import { useResearchSymbolSelection } from "../research-symbols/useResearchSymbolSelection";
import { DashboardMarketCards } from "./DashboardMarketCards";
import { RecentReportCard } from "./RecentReportCard";

export function DashboardPage() {
  const api = useWorkbenchApi();
  const selection = useResearchSymbolSelection();
  const dashboardQuery = useQuery({
    queryKey: ["dashboard", selection.selected],
    enabled:
      selection.catalogQuery.isSuccess &&
      selection.selected !== undefined &&
      !selection.invalid,
    queryFn: () => {
      if (selection.selected === undefined) {
        throw new Error("Research symbol is unavailable");
      }
      return api.getDashboard({ symbol: selection.selected });
    },
  });
  const symbolSelector = (
    <ResearchSymbolSelect
      entries={selection.entries}
      value={selection.selected}
      pending={selection.catalogQuery.isPending}
      onValueChange={selection.select}
    />
  );

  if (selection.catalogQuery.isPending) {
    return (
      <section className="research-page dashboard-page">
        <header className="research-page__heading">
          <div><p className="route-page__kicker">研究与模拟工作台</p><h1>研究工作台</h1></div>
          {symbolSelector}
        </header>
        <PageState state="loading" />
      </section>
    );
  }

  if (
    selection.catalogQuery.isError ||
    selection.invalid ||
    selection.selected === undefined
  ) {
    return (
      <section className="research-page dashboard-page">
        <header className="research-page__heading">
          <div><p className="route-page__kicker">研究与模拟工作台</p><h1>研究工作台</h1></div>
          {symbolSelector}
        </header>
        <PageState state="unavailable" message="URL 中的研究币对未登记或无效，请从下拉列表选择。" />
      </section>
    );
  }

  if (dashboardQuery.isPending) {
    return (
      <section className="research-page dashboard-page">
        <header className="research-page__heading">
          <div><p className="route-page__kicker">研究与模拟工作台</p><h1>研究工作台</h1></div>
          {symbolSelector}
        </header>
        <PageState state="loading" />
      </section>
    );
  }

  if (dashboardQuery.isError) {
    const isPublicMarketUnavailable =
      dashboardQuery.error instanceof WorkbenchHttpError &&
      dashboardQuery.error.code.startsWith("market_data_");
    return (
      <PageState
        state="error"
        message={
          isPublicMarketUnavailable
            ? "公开行情暂不可用，请检查后端服务、网络或数据源状态后重试。"
            : "无法读取研究工作台数据，请稍后重试。"
        }
      />
    );
  }

  const dashboard = dashboardQuery.data;
  if (
    dashboard.markets.length === 0 &&
    dashboard.news.length === 0 &&
    dashboard.recentReports.length === 0
  ) {
    return (
      <PageState
        state="empty"
        message="当前没有可显示的市场研究数据。"
      />
    );
  }

  return (
    <section className="research-page dashboard-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">研究与模拟工作台</p>
          <h1>研究工作台</h1>
          <p>
            汇总可追溯市场摘要、公开资讯与历史研究结果，仅用于研究和界面验证。
          </p>
        </div>
        <p className="snapshot-time">
          快照生成时间：
          <time dateTime={dashboard.generatedAt}>
            {dashboard.generatedAt}
          </time>
        </p>
        {symbolSelector}
      </header>

      {dashboard.markets.length > 0 ? (
        <section aria-labelledby="dashboard-markets-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">MARKET SNAPSHOT</p>
              <h2 id="dashboard-markets-title">市场摘要</h2>
            </div>
          </div>
          <DashboardMarketCards markets={dashboard.markets} />
        </section>
      ) : (
        <PageState state="empty" message="暂无市场摘要数据。" />
      )}

      <div className="dashboard-page__columns">
        <section aria-labelledby="dashboard-news-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">PUBLIC SOURCES</p>
              <h2 id="dashboard-news-title">资讯摘要</h2>
            </div>
          </div>
          {dashboard.news.length > 0 ? (
            <div className="news-card-list">
              {dashboard.news.map((item) => (
                <article className="news-card" key={item.id}>
                  <h3>{item.title}</h3>
                  <p>{item.summary}</p>
                  <a
                    className="text-link"
                    href={item.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {item.source}
                  </a>
                  <dl className="metadata-list">
                    <div>
                      <dt>发布时间</dt>
                      <dd>
                        <time dateTime={item.publishedAt}>
                          {item.publishedAt}
                        </time>
                      </dd>
                    </div>
                    <div>
                      <dt>获取时间</dt>
                      <dd>
                        <time dateTime={item.fetchedAt}>
                          {item.fetchedAt}
                        </time>
                      </dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          ) : (
            <PageState state="empty" message="暂无资讯摘要。" />
          )}
        </section>

        <section aria-labelledby="dashboard-reports-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">RESEARCH HISTORY</p>
              <h2 id="dashboard-reports-title">最近研究报告</h2>
            </div>
          </div>
          {dashboard.recentReports.length > 0 ? (
            <div className="report-card-list">
              {dashboard.recentReports.map((report) => (
                <RecentReportCard report={report} key={report.id} />
              ))}
            </div>
          ) : (
            <PageState state="empty" message="暂无历史研究报告。" />
          )}
        </section>
      </div>
    </section>
  );
}
