import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import { rememberResearchSymbol, useResearchSymbolSelection } from "./useResearchSymbolSelection";

export function ResearchSymbolManagementPage() {
  const api = useWorkbenchApi();
  const queryClient = useQueryClient();
  const { catalogQuery, entries } = useResearchSymbolSelection();
  const [symbol, setSymbol] = useState("");
  const addMutation = useMutation({
    mutationFn: () => api.addResearchSymbol({ symbol }),
    onSuccess: (entry) => {
      rememberResearchSymbol(entry.symbol);
      setSymbol("");
      void queryClient.invalidateQueries({ queryKey: ["research-symbols"] });
    },
  });
  const archiveMutation = useMutation({
    mutationFn: (target: string) => api.archiveResearchSymbol(target),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["research-symbols"] });
    },
  });

  return (
    <section className="research-page research-symbol-management-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">RESEARCH DIRECTORY</p>
          <h1>研究币对管理</h1>
          <p>添加前会验证公开行情、K 线与衍生品数据；通过后自动排队同步。</p>
        </div>
      </header>

      <form
        className="research-symbol-form"
        onSubmit={(event) => {
          event.preventDefault();
          addMutation.mutate();
        }}
      >
        <label>
          币对
          <input
            aria-label="币对"
            value={symbol}
            placeholder="例如 SOLUSDT"
            onChange={(event) => setSymbol(event.target.value)}
          />
        </label>
        <button
          className="primary-action"
          type="submit"
          disabled={!symbol.trim() || addMutation.isPending}
        >
          检查并添加
        </button>
      </form>
      {addMutation.isError ? (
        <p className="inline-error" role="alert">
          当前币对不满足研究数据要求，请检查合约状态后重试。
        </p>
      ) : null}

      {catalogQuery.isPending ? <PageState state="loading" /> : null}
      {catalogQuery.isError ? (
        <PageState state="error" message="无法读取研究币对目录。" />
      ) : null}
      {catalogQuery.isSuccess ? (
        <div className="research-symbol-list">
          {entries.map((entry) => {
            const etf = entry.capabilities.find((item) => item.name === "etf");
            return (
              <article aria-label={entry.symbol} className="research-symbol-card" key={entry.symbol}>
                <header>
                  <h2>{entry.symbol}</h2>
                  <span>{entry.canResearch ? "可研究" : "同步中"}</span>
                </header>
                {entry.symbol === "BTCUSDT" || entry.symbol === "ETHUSDT" ? null : (
                  <p>离线示例会在本地展示可验证的样例数据。</p>
                )}
                {etf === undefined ? null : <p>ETF 专题：{etf.message}</p>}
                <button
                  className="secondary-action"
                  type="button"
                  disabled={archiveMutation.isPending}
                  onClick={() => archiveMutation.mutate(entry.symbol)}
                >
                  删除
                </button>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
