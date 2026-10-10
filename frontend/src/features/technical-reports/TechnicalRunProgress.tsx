import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkbenchApi } from "../../app/providers";

const phases = {queued: "等待开始", collecting: "采集并冻结行情", analyzing: "思考分析交易情景", validating: "校验分析与证据", composing: "编排交易计划书", saving: "保存报告", finished: "生成结束"};

export function TechnicalRunProgress({runId, symbol}: {runId: string; symbol: string}) {
  const api = useWorkbenchApi();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const query = useQuery({queryKey: ["technical-run", runId], queryFn: () => api.getTechnicalReportRun(runId), refetchInterval: q => q.state.status === "error" ? false : q.state.data === undefined || ["queued", "running"].includes(q.state.data.status) ? 2000 : false});
  const run = query.data;
  useEffect(() => {
    if (run === undefined || run.symbol !== symbol || run.reportId === null || !["completed", "degraded"].includes(run.status)) return;
    localStorage.removeItem(`technical-run:${symbol}`);
    localStorage.removeItem(`technical-request:${symbol}`);
    void cache.invalidateQueries({queryKey: ["technical-reports", symbol]});
    void navigate(`/technical-reports/${encodeURIComponent(run.reportId)}`, {replace: true});
  }, [run, symbol, cache, navigate]);
  if (run !== undefined && run.symbol !== symbol) return <p role="alert">任务币对与当前选择不一致，请切换到对应币对查看。</p>;
  return <div className="technical-notice" aria-label="技术报告生成进度">
    <p role="status">{run === undefined ? "正在查询任务状态" : phases[run.phase]}</p>
    <p>任务 ID：{runId}。可刷新页面继续查看；思考分析可能需要数分钟。</p>
    {query.isError ? <><p role="alert">任务状态查询暂不可用，任务可能仍在运行。</p><button type="button" onClick={() => {void query.refetch();}}>重试查询</button></> : null}
    {run?.status === "failed" ? <p role="alert">{run.errorCode === "interrupted" ? "生成被中断，没有自动重新调用模型。" : run.errorCode === "symbol_not_admitted" ? "币对已不满足研究准入条件。" : "任务生成失败，请稍后重新研究。"}</p> : null}
  </div>;
}
