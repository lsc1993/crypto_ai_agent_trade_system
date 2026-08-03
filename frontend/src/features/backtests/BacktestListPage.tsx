import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type {
  BacktestRequest,
  BacktestRunSummary,
} from "../../domain/backtest";
import { formatDecimal } from "../../shared/format";
import { BacktestForm } from "./BacktestForm";

const statusLabels = {
  pending: "处理中",
  completed: "已完成",
  failed: "失败",
} as const;

function BacktestRunTable({ runs }: { runs: BacktestRunSummary[] }) {
  return (
    <div className="table-scroll">
      <table className="market-table" aria-label="回测运行记录">
        <thead>
          <tr>
            <th scope="col">状态</th>
            <th scope="col">标的</th>
            <th scope="col">时间范围（UTC）</th>
            <th scope="col">初始资金</th>
            <th scope="col">净盈亏</th>
            <th scope="col">创建时间（UTC）</th>
            <th scope="col">记录操作</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{statusLabels[run.status]}</td>
              <td>
                {run.symbol} · {run.timeframe}
              </td>
              <td>
                <time dateTime={run.startAt}>{run.startAt}</time>
                <br />
                <time dateTime={run.endAt}>{run.endAt}</time>
              </td>
              <td>{formatDecimal(run.initialCash)} USDT</td>
              <td>
                {run.summary === null
                  ? "结果未完成"
                  : `${formatDecimal(run.summary.netPnl)} USDT`}
              </td>
              <td>
                <time dateTime={run.createdAt}>{run.createdAt}</time>
              </td>
              <td>
                <Link
                  className="text-link"
                  to={`/backtests/${encodeURIComponent(run.id)}`}
                >
                  查看回测详情
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BacktestListPage() {
  const api = useWorkbenchApi();
  const navigate = useNavigate();
  const runsQuery = useQuery({
    queryKey: ["backtests", { page: 1, pageSize: 20 }],
    queryFn: () => api.listBacktests({ page: 1, pageSize: 20 }),
  });
  const startMutation = useMutation({
    mutationFn: (input: BacktestRequest) => api.startBacktest(input),
    onSuccess: (run) => {
      void navigate(`/backtests/${encodeURIComponent(run.id)}`);
    },
  });

  let historyContent;
  if (runsQuery.isPending) {
    historyContent = <PageState state="loading" />;
  } else if (runsQuery.isError) {
    historyContent = (
      <PageState
        state="error"
        message="无法读取回测记录，请稍后重试。"
      />
    );
  } else if (runsQuery.data === undefined) {
    historyContent = (
      <PageState
        state="unavailable"
        message="回测记录暂不可用，请稍后重试。"
      />
    );
  } else if (runsQuery.data.items.length === 0) {
    historyContent = <PageState state="empty" message="暂无历史回测记录。" />;
  } else {
    historyContent = <BacktestRunTable runs={runsQuery.data.items} />;
  }

  return (
    <section className="research-page backtests-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">可审计历史模拟</p>
          <h1>策略回测</h1>
          <p>
            回测以确定性规则重放历史行情，结果仅用于研究与复盘，不构成交易建议或交易执行。
          </p>
        </div>
      </header>

      <BacktestForm
        isSubmitting={startMutation.isPending}
        submissionFailed={startMutation.isError}
        onSubmit={startMutation.mutate}
      />

      <section aria-labelledby="backtests-history-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">AUDITABLE HISTORY</p>
            <h2 id="backtests-history-title">回测运行记录</h2>
          </div>
        </div>
        {historyContent}
      </section>
    </section>
  );
}
