import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Decimal from "decimal.js";
import { Link, useParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import {
  uuidSchema,
  type DecimalString,
} from "../../domain/primitives";
import type {
  ManualPaperIntent,
  PaperAccountDetail,
} from "../../domain/paper-trading";
import { formatDecimal } from "../../shared/format";

const eventLabels: Record<
  PaperAccountDetail["events"][number]["kind"],
  string
> = {
  intent: "交易意图",
  no_signal: "无信号",
  market_unavailable: "市场不可用",
  risk_approved: "风控通过",
  risk_rejected: "风控拒绝",
  risk_exit: "风控退出",
  order: "模拟订单",
  fill: "模拟成交",
  archived: "账户归档",
};

const outcomeLabels: Record<
  NonNullable<PaperAccountDetail["actionOutcome"]>["kind"],
  string
> = {
  filled: "已模拟成交",
  risk_rejected: "风控拒绝",
  no_signal: "无信号",
  risk_exit: "风控退出",
};

function isZero(value: DecimalString): boolean {
  return /^0(?:\.0+)?$/.test(value);
}

function formatPercent(value: DecimalString): string {
  return `${formatDecimal(new Decimal(value).mul(100).toFixed(2))}%`;
}

function PaperAccountDetails({ account }: { account: PaperAccountDetail }) {
  const api = useWorkbenchApi();
  const queryClient = useQueryClient();
  const invalidateAccount = (updatedAccount: PaperAccountDetail) => {
    queryClient.setQueryData(["paper-account", account.id], updatedAccount);
    void queryClient.invalidateQueries({ queryKey: ["paper-accounts"] });
    void queryClient.invalidateQueries({
      queryKey: ["paper-account", account.id],
    });
  };
  const openMutation = useMutation({
    mutationFn: (input: ManualPaperIntent) =>
      api.submitPaperManualIntent(account.id, input),
    onSuccess: invalidateAccount,
  });
  const closeMutation = useMutation({
    mutationFn: (input: ManualPaperIntent) =>
      api.submitPaperManualIntent(account.id, input),
    onSuccess: invalidateAccount,
  });
  const strategyMutation = useMutation({
    mutationFn: () => api.evaluatePaperStrategy(account.id),
    onSuccess: invalidateAccount,
  });
  const archiveMutation = useMutation({
    mutationFn: () => api.archivePaperAccount(account.id),
    onSuccess: invalidateAccount,
  });

  function submitManualIntent(action: ManualPaperIntent["action"]) {
    const input: ManualPaperIntent = {
      clientRequestId: crypto.randomUUID(),
      action,
    };
    if (action === "open_long") {
      openMutation.mutate(input);
      return;
    }
    closeMutation.mutate(input);
  }

  function confirmArchive() {
    if (!window.confirm("确认归档此模拟盘？归档后仅可查看历史记录。")) {
      return;
    }
    archiveMutation.mutate();
  }

  const active = account.status === "active";
  const positionIsFlat = isZero(account.position.quantity);
  const mutationError = openMutation.isError
    ? "无法执行手动开多，请稍后重试。"
    : closeMutation.isError
      ? "无法执行手动平多，请稍后重试。"
      : strategyMutation.isError
        ? "无法运行策略评估，请稍后重试。"
        : archiveMutation.isError
          ? "无法归档模拟盘，请稍后重试。"
          : null;

  return (
    <section className="research-page paper-trading-detail">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">IMMUTABLE LOCAL SIMULATION</p>
          <h1>模拟盘详情</h1>
          <p>
            当前状态：{active ? "活跃" : "已归档"}。仅使用公开行情生成本地模拟结果，绝不连接真实账户或下单。
          </p>
        </div>
        <Link className="text-link" to="/paper-trading">
          返回模拟盘
        </Link>
      </header>

      <section className="paper-detail-section" aria-labelledby="paper-account-overview-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">ACCOUNT OVERVIEW</p>
            <h2 id="paper-account-overview-title">账户与仓位</h2>
          </div>
        </div>
        <dl className="paper-account-metrics">
          <div><dt>账户 ID</dt><dd>{account.id}</dd></div>
          <div><dt>标的</dt><dd>{account.symbol}</dd></div>
          <div><dt>初始资金</dt><dd>{formatDecimal(account.initialCash)} USDT</dd></div>
          <div><dt>现金</dt><dd>{formatDecimal(account.cash)} USDT</dd></div>
          <div><dt>权益</dt><dd>{formatDecimal(account.equity)} USDT</dd></div>
          <div><dt>峰值权益</dt><dd>{formatDecimal(account.peakEquity)} USDT</dd></div>
          <div><dt>BTC 仓位</dt><dd>{formatDecimal(account.position.quantity)} BTC</dd></div>
          <div><dt>平均开仓价</dt><dd>{account.position.averageEntryPrice === null ? "无" : `${formatDecimal(account.position.averageEntryPrice)} USDT`}</dd></div>
        </dl>
      </section>

      <section className="paper-detail-section" aria-labelledby="paper-market-snapshot-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">PUBLIC MARKET SNAPSHOT</p>
            <h2 id="paper-market-snapshot-title">行情快照</h2>
          </div>
        </div>
        {account.latestSnapshot === null ? (
          <PageState state="empty" message="尚未产生可审计的模拟成交行情快照。" />
        ) : (
          <dl className="metadata-list">
            <div><dt>价格</dt><dd>{formatDecimal(account.latestSnapshot.price)} USDT</dd></div>
            <div><dt>来源</dt><dd>{account.latestSnapshot.source}</dd></div>
            <div><dt>观察时间（UTC）</dt><dd><time dateTime={account.latestSnapshot.observedAt}>{account.latestSnapshot.observedAt}</time></dd></div>
            <div><dt>获取时间（UTC）</dt><dd><time dateTime={account.latestSnapshot.fetchedAt}>{account.latestSnapshot.fetchedAt}</time></dd></div>
            <div><dt>载荷哈希</dt><dd>{account.latestSnapshot.payloadHash}</dd></div>
          </dl>
        )}
      </section>

      <section className="paper-detail-section" aria-labelledby="paper-configuration-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">FROZEN RISK AND EXECUTION</p>
            <h2 id="paper-configuration-title">风控与成交假设</h2>
          </div>
        </div>
        <dl className="paper-account-metrics">
          <div><dt>最大敞口</dt><dd>{formatPercent(account.riskConfig.maxExposureFraction)}</dd></div>
          <div><dt>止损阈值</dt><dd>{formatPercent(account.riskConfig.stopLossFraction)}</dd></div>
          <div><dt>单日最大亏损</dt><dd>{formatPercent(account.riskConfig.dailyLossFraction)}</dd></div>
          <div><dt>最大回撤</dt><dd>{formatPercent(account.riskConfig.maxDrawdownFraction)}</dd></div>
          <div><dt>冷却 K 线</dt><dd>{account.riskConfig.cooldownCandles}</dd></div>
          <div><dt>数量精度</dt><dd>{formatDecimal(account.riskConfig.quantityIncrement)} BTC</dd></div>
          <div><dt>手续费率</dt><dd>{formatPercent(account.executionConfig.feeRate)}</dd></div>
          <div><dt>滑点率</dt><dd>{formatPercent(account.executionConfig.slippageRate)}</dd></div>
          <div><dt>成交比例</dt><dd>{formatPercent(account.executionConfig.fillRatio)}</dd></div>
        </dl>
      </section>

      {active ? (
        <section className="paper-detail-section" aria-labelledby="paper-actions-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">MANUAL SIMULATION ONLY</p>
              <h2 id="paper-actions-title">模拟操作</h2>
            </div>
          </div>
          <p className="paper-detail-section__description">
            每次操作将获取公开 BTCUSDT 行情，经过确定性风控校验后写入本地不可变审计记录。
          </p>
          <div className="paper-action-controls">
            <button
              className="primary-action"
              type="button"
              disabled={openMutation.isPending}
              onClick={() => submitManualIntent("open_long")}
            >
              {openMutation.isPending ? "正在手动开多" : "手动开多"}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={closeMutation.isPending}
              onClick={() => submitManualIntent("close_long")}
            >
              {closeMutation.isPending ? "正在手动平多" : "手动平多"}
            </button>
            <button
              className="secondary-action"
              type="button"
              disabled={strategyMutation.isPending}
              onClick={() => strategyMutation.mutate()}
            >
              {strategyMutation.isPending
                ? "正在运行 SMA 策略评估"
                : "运行 SMA 策略评估"}
            </button>
          </div>
          {positionIsFlat ? (
            <button
              className="paper-archive-action"
              type="button"
              disabled={archiveMutation.isPending}
              onClick={confirmArchive}
            >
              {archiveMutation.isPending ? "正在归档模拟盘" : "归档模拟盘"}
            </button>
          ) : (
            <p className="paper-detail-section__description">
              仅平仓后才能归档模拟盘。
            </p>
          )}
          {mutationError === null ? null : (
            <p className="inline-error" role="alert">{mutationError}</p>
          )}
        </section>
      ) : null}

      {account.actionOutcome === null ? null : (
        <section className="paper-detail-section" aria-labelledby="paper-outcome-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">LATEST DETERMINISTIC OUTCOME</p>
              <h2 id="paper-outcome-title">最近操作结果</h2>
            </div>
          </div>
          <p className="paper-detail-section__description">
            {outcomeLabels[account.actionOutcome.kind]}
            {account.actionOutcome.source === null ? "" : ` · 来源：${account.actionOutcome.source}`}
            {account.actionOutcome.reason === null ? "" : ` · ${account.actionOutcome.reason}`}
          </p>
        </section>
      )}

      <section className="paper-detail-section" aria-labelledby="paper-orders-title">
        <div className="section-heading"><div><p className="section-kicker">SIMULATED ORDERS</p><h2 id="paper-orders-title">模拟订单</h2></div></div>
        <div className="table-scroll"><table className="market-table" aria-label="模拟订单"><thead><tr><th scope="col">动作</th><th scope="col">提交时间（UTC）</th><th scope="col">请求数量</th><th scope="col">状态</th><th scope="col">幂等键</th></tr></thead><tbody>{account.orders.length === 0 ? <tr><td colSpan={5}>暂无模拟订单。</td></tr> : account.orders.map((order) => <tr key={order.idempotencyKey}><td>{order.action === "open_long" ? "开多" : "平多"}</td><td><time dateTime={order.submittedAt}>{order.submittedAt}</time></td><td>{formatDecimal(order.requestedQuantity)} BTC</td><td>{order.status}</td><td>{order.idempotencyKey}</td></tr>)}</tbody></table></div>
      </section>

      <section className="paper-detail-section" aria-labelledby="paper-fills-title">
        <div className="section-heading"><div><p className="section-kicker">SIMULATED FILLS</p><h2 id="paper-fills-title">模拟成交</h2></div></div>
        <div className="table-scroll"><table className="market-table" aria-label="模拟成交"><thead><tr><th scope="col">动作</th><th scope="col">成交时间（UTC）</th><th scope="col">数量</th><th scope="col">价格</th><th scope="col">手续费</th><th scope="col">订单幂等键</th></tr></thead><tbody>{account.fills.length === 0 ? <tr><td colSpan={6}>暂无模拟成交。</td></tr> : account.fills.map((fill) => <tr key={`${fill.orderIdempotencyKey}-${fill.filledAt}`}><td>{fill.action === "open_long" ? "开多" : "平多"}</td><td><time dateTime={fill.filledAt}>{fill.filledAt}</time></td><td>{formatDecimal(fill.quantity)} BTC</td><td>{formatDecimal(fill.price)} USDT</td><td>{formatDecimal(fill.fee)} USDT</td><td>{fill.orderIdempotencyKey}</td></tr>)}</tbody></table></div>
      </section>

      <section className="paper-detail-section" aria-labelledby="paper-ledger-title">
        <div className="section-heading"><div><p className="section-kicker">CASH AND POSITION LEDGER</p><h2 id="paper-ledger-title">资金与仓位流水</h2></div></div>
        <div className="table-scroll"><table className="market-table" aria-label="资金与仓位流水"><thead><tr><th scope="col">发生时间（UTC）</th><th scope="col">动作</th><th scope="col">现金变动</th><th scope="col">仓位变动</th><th scope="col">已实现盈亏</th><th scope="col">手续费</th></tr></thead><tbody>{account.ledgerEntries.length === 0 ? <tr><td colSpan={6}>暂无资金与仓位流水。</td></tr> : account.ledgerEntries.map((entry) => <tr key={`${entry.occurredAt}-${entry.kind}`}><td><time dateTime={entry.occurredAt}>{entry.occurredAt}</time></td><td>{entry.kind === "open_long" ? "开多" : "平多"}</td><td>{formatDecimal(entry.cashDelta, { showPositiveSign: true })} USDT</td><td>{formatDecimal(entry.positionDelta, { showPositiveSign: true })} BTC</td><td>{formatDecimal(entry.realizedPnl, { showPositiveSign: true })} USDT</td><td>{formatDecimal(entry.fee)} USDT</td></tr>)}</tbody></table></div>
      </section>

      <section className="paper-detail-section" aria-labelledby="paper-events-title">
        <div className="section-heading"><div><p className="section-kicker">IMMUTABLE AUDIT EVENTS</p><h2 id="paper-events-title">审计事件</h2></div></div>
        <div className="table-scroll"><table className="market-table" aria-label="模拟盘审计事件"><thead><tr><th scope="col">序号</th><th scope="col">事件</th><th scope="col">发生时间（UTC）</th><th scope="col">幂等键</th><th scope="col">审计载荷</th></tr></thead><tbody>{account.events.length === 0 ? <tr><td colSpan={5}>暂无审计事件。</td></tr> : account.events.map((event) => <tr key={event.sequence}><td>{event.sequence}</td><td>{eventLabels[event.kind]}</td><td><time dateTime={event.occurredAt}>{event.occurredAt}</time></td><td>{event.idempotencyKey ?? "不适用"}</td><td><code>{JSON.stringify(event.payload)}</code></td></tr>)}</tbody></table></div>
      </section>
    </section>
  );
}

function PaperAccountDetailContent({ accountId }: { accountId: string }) {
  const api = useWorkbenchApi();
  const accountQuery = useQuery({
    queryKey: ["paper-account", accountId],
    queryFn: () => api.getPaperAccount(accountId),
  });

  if (accountQuery.isPending) {
    return <PageState state="loading" />;
  }
  if (accountQuery.isError) {
    return (
      <PageState
        state="error"
        message="无法读取模拟盘详情，请稍后重试。"
      />
    );
  }
  if (accountQuery.data === undefined) {
    return (
      <PageState
        state="unavailable"
        message="模拟盘详情暂不可用，请稍后重试。"
      />
    );
  }
  return <PaperAccountDetails account={accountQuery.data} />;
}

export function PaperAccountDetailPage() {
  const { accountId } = useParams();
  const parsedAccountId =
    accountId === undefined ? null : uuidSchema.safeParse(accountId);
  if (parsedAccountId === null || !parsedAccountId.success) {
    return (
      <PageState
        state="unavailable"
        message="未提供有效的模拟盘账户标识。"
      />
    );
  }
  return (
    <PaperAccountDetailContent
      key={parsedAccountId.data}
      accountId={parsedAccountId.data}
    />
  );
}
