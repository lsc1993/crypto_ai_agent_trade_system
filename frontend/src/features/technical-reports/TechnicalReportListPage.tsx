import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import { symbolSchema } from "../../domain/primitives";
import { MockWorkbenchApi } from "../../shared/api/mock-workbench-api";
import { ResearchSymbolSelect } from "../research-symbols/ResearchSymbolSelect";
import { errorLabel, requestErrorLabel } from "./technical-copy";
import { ReportStyleNavigation } from "./ReportStyleNavigation";

const PAGE_SIZE = 20;

export function TechnicalReportListPage() {
  return <><ReportStyleNavigation selected="technical" /><TechnicalReportList /></>;
}

function TechnicalReportGenerator({ symbol }: { symbol: string }) {
  const api = useWorkbenchApi();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function generate() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setErrorMessage(null);
    try {
      const report = await api.startTechnicalReport({ symbol });
      await queryClient.invalidateQueries({ queryKey: ["technical-reports", symbol] });
      if (mounted.current) void navigate(`/technical-reports/${encodeURIComponent(report.id)}`);
    } catch (error) {
      if (mounted.current) setErrorMessage(requestErrorLabel(error));
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }
  return <section className="technical-action" aria-label="生成技术研究">
    <p>当前币对：<strong>{symbol}</strong>。每次生成会保存独立报告；条件计划仅供研究复核，不会提交订单。</p>
    <button className="primary-action" type="button" disabled={pending} onClick={() => { void generate(); }}>生成技术报告</button>
    {pending ? <p role="status">正在计算并保存技术报告，请稍候。</p> : null}
    {errorMessage === null ? null : <p role="alert" className="inline-error">{errorMessage}</p>}
  </section>;
}

function TechnicalReportList() {
  const api = useWorkbenchApi();
  const [params, setParams] = useSearchParams();
  const catalog = useQuery({ queryKey: ["research-symbols"], queryFn: () => api.listResearchSymbols() });
  const requested = params.get("symbol");
  const activeEntries = (catalog.data ?? []).filter((entry) => entry.canResearch);
  const selected = requested ?? activeEntries[0]?.symbol;
  const invalid = requested !== null && !symbolSchema.safeParse(requested).success;
  const active = activeEntries.some((entry) => entry.symbol === selected);
  const selectedEntry = catalog.data?.find((entry) => entry.symbol === selected);
  const pageValue = Number(params.get("page") ?? "1");
  const page = Number.isSafeInteger(pageValue) && pageValue > 0 ? pageValue : 1;
  const reports = useQuery({
    queryKey: ["technical-reports", selected, page],
    enabled: catalog.isSuccess && !invalid,
    queryFn: () => api.listTechnicalReports({ symbol: selected, page, pageSize: PAGE_SIZE }),
  });

  if (catalog.isPending) return <PageState state="loading" />;
  if (catalog.isError) return <PageState state="error" message="无法读取研究币对目录，请稍后重试。" />;
  if (invalid) return <PageState state="unavailable" message="URL 中的研究币对格式无效。" />;

  return (
    <section className="research-page technical-reports-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">独立技术研究 · 只读</p>
          <h1>技术分析报告</h1>
          <p>使用公开行情的日线、4 小时与 1 小时已收盘 K 线，按量价、区间突破及多周期方法生成冻结研究记录。</p>
        </div>
        {selected === undefined ? null : <ResearchSymbolSelect entries={activeEntries} value={selected} pending={catalog.isPending} onValueChange={(symbol) => {
          const next = new URLSearchParams(params);
          next.set("symbol", symbol);
          next.delete("page");
          setParams(next);
        }} />}
      </header>
      {api instanceof MockWorkbenchApi ? <p className="technical-notice">Mock 演示数据：不会读取真实行情，也不会生成真实 AI 结论。</p> : null}
      {selected === undefined ? <p className="technical-notice">当前没有就绪的研究币对，下方展示全部历史报告。可前往研究币对管理添加币对或查看同步状态。</p> : !active ? <p className="technical-notice">{selected} {selectedEntry?.enabled ? "数据尚未就绪；请在研究币对管理中查看同步状态。已有历史报告仍可读取。" : "已归档或未在当前研究目录中；可读取已有历史报告，不能新建研究。"}</p> : (
        <TechnicalReportGenerator key={selected} symbol={selected} />
      )}
      <section className="technical-history" aria-labelledby="technical-history-title">
        <h2 id="technical-history-title">历史报告</h2>
        {reports.isPending ? <PageState state="loading" /> : reports.isError ? <PageState state="error" message="历史技术报告读取失败，请稍后重试。" /> : reports.data.items.length === 0 ? <PageState state="empty" message="该币对暂无历史技术报告。" /> : (
          <div className="technical-history__list">
            {reports.data.items.map((report) => (
              <article className="report-card" key={report.id}>
                <header className="report-card__header"><h3>{report.symbol} · {report.status === "completed" ? "已完成" : "已降级"}</h3></header>
                <p>{errorLabel(report.errorCode) ?? "技术事实及定性分析已冻结。"}</p>
                <p>数据截止（UTC）：<time dateTime={report.dataCutoffAt}>{report.dataCutoffAt}</time></p>
                <Link className="text-link" to={`/technical-reports/${encodeURIComponent(report.id)}`}>查看技术报告</Link>
              </article>
            ))}
          </div>
        )}
        {reports.data !== undefined && reports.data.total > PAGE_SIZE ? <nav className="technical-pagination" aria-label="历史报告分页">
          <button type="button" disabled={page <= 1} onClick={() => { const next = new URLSearchParams(params); next.set("page", String(page - 1)); setParams(next); }}>上一页</button>
          <span>第 {page} 页，共 {Math.ceil(reports.data.total / PAGE_SIZE)} 页</span>
          <button type="button" disabled={page * PAGE_SIZE >= reports.data.total} onClick={() => { const next = new URLSearchParams(params); next.set("page", String(page + 1)); setParams(next); }}>下一页</button>
        </nav> : null}
      </section>
    </section>
  );
}
