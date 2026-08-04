import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type {
  PaperAccountCreate,
  PaperAccountSummary,
} from "../../domain/paper-trading";
import { formatDecimal } from "../../shared/format";
import { PaperAccountForm } from "./PaperAccountForm";

const mockModeRequirement = "模拟盘需要本地 API 与数据库";

function safeListErrorMessage(error: unknown): string {
  return error instanceof Error && error.message === mockModeRequirement
    ? mockModeRequirement
    : "无法读取模拟盘账户，请稍后重试。";
}

function statusLabel(status: PaperAccountSummary["status"]): string {
  return status === "active" ? "活跃" : "已归档";
}

function PaperAccountTable({ accounts }: { accounts: PaperAccountSummary[] }) {
  return (
    <div className="table-scroll">
      <table className="market-table" aria-label="模拟盘账户记录">
        <thead>
          <tr>
            <th scope="col">状态</th>
            <th scope="col">标的</th>
            <th scope="col">现金</th>
            <th scope="col">权益</th>
            <th scope="col">BTC 仓位</th>
            <th scope="col">创建时间（UTC）</th>
            <th scope="col">记录操作</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <tr key={account.id}>
              <td>{statusLabel(account.status)}</td>
              <td>{account.symbol}</td>
              <td>{formatDecimal(account.cash)} USDT</td>
              <td>{formatDecimal(account.equity)} USDT</td>
              <td>{formatDecimal(account.positionQuantity)} BTC</td>
              <td>
                <time dateTime={account.createdAt}>{account.createdAt}</time>
              </td>
              <td>
                <Link
                  className="text-link"
                  to={`/paper-trading/${encodeURIComponent(account.id)}`}
                >
                  查看模拟盘详情
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PaperAccountListPage() {
  const api = useWorkbenchApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accountsQuery = useQuery({
    queryKey: ["paper-accounts", { page: 1, pageSize: 20 }],
    queryFn: () => api.listPaperAccounts({ page: 1, pageSize: 20 }),
  });
  const createMutation = useMutation({
    mutationFn: (input: PaperAccountCreate) => api.createPaperAccount(input),
    onSuccess: (account) => {
      queryClient.setQueryData(["paper-account", account.id], account);
      void queryClient.invalidateQueries({ queryKey: ["paper-accounts"] });
      void queryClient.invalidateQueries({
        queryKey: ["paper-account", account.id],
      });
      void navigate(`/paper-trading/${encodeURIComponent(account.id)}`);
    },
  });

  let accountContent;
  if (accountsQuery.isPending) {
    accountContent = <PageState state="loading" />;
  } else if (accountsQuery.isError) {
    accountContent = (
      <PageState
        state="error"
        message={safeListErrorMessage(accountsQuery.error)}
      />
    );
  } else if (accountsQuery.data === undefined) {
    accountContent = (
      <PageState
        state="unavailable"
        message="模拟盘账户暂不可用，请稍后重试。"
      />
    );
  } else {
    const activeAccount = accountsQuery.data.items.find(
      (account) => account.status === "active",
    );
    accountContent = (
      <>
        {activeAccount === undefined ? (
          <PaperAccountForm
            isSubmitting={createMutation.isPending}
            submissionFailed={createMutation.isError}
            onSubmit={createMutation.mutate}
          />
        ) : (
          <section className="paper-account-current" aria-labelledby="current-paper-account-title">
            <div>
              <p className="section-kicker">CURRENT PAPER ACCOUNT</p>
              <h2 id="current-paper-account-title">当前模拟盘</h2>
              <p>
                BTCUSDT · 权益 {formatDecimal(activeAccount.equity)} USDT ·
                仓位 {formatDecimal(activeAccount.positionQuantity)} BTC
              </p>
            </div>
            <Link
              className="primary-link"
              to={`/paper-trading/${encodeURIComponent(activeAccount.id)}`}
            >
              打开当前模拟盘
            </Link>
          </section>
        )}
        {accountsQuery.data.items.length === 0 ? null : (
          <section aria-labelledby="paper-account-history-title">
            <div className="section-heading">
              <div>
                <p className="section-kicker">AUDITABLE ACCOUNT HISTORY</p>
                <h2 id="paper-account-history-title">模拟盘账户记录</h2>
              </div>
            </div>
            <PaperAccountTable accounts={accountsQuery.data.items} />
          </section>
        )}
      </>
    );
  }

  return (
    <section className="research-page paper-trading-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">LOCAL AUDITABLE SIMULATION</p>
          <h1>模拟盘</h1>
          <p>仅模拟，不连接真实账户或产生真实订单。</p>
        </div>
      </header>
      {accountContent}
    </section>
  );
}
