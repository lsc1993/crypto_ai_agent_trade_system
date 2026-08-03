import Decimal from "decimal.js";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import type {
  BacktestAuditEvent,
  BacktestRunDetail,
} from "../../domain/backtest";
import type { DecimalString } from "../../domain/primitives";
import { formatDecimal } from "../../shared/format";

const statusLabels = {
  pending: "处理中",
  completed: "已完成",
  failed: "失败",
} as const;

const eventLabels: Record<BacktestAuditEvent["kind"], string> = {
  decision: "策略决策",
  risk_approved: "风控通过",
  risk_rejected: "风控拒绝",
  order: "模拟订单",
  fill: "模拟成交",
  risk_exit: "风控退出",
  circuit_breaker: "熔断",
  completed: "回测完成",
};

function formatPercent(value: DecimalString): string {
  const percentage = new Decimal(value).mul(100).toFixed(2);
  return `${formatDecimal(percentage)}%`;
}

function hasOpenPosition(quantity: DecimalString): boolean {
  return !/^0(?:\.0+)?$/.test(quantity);
}

function BacktestResult({ run }: { run: BacktestRunDetail }) {
  const summary = run.summary;
  if (summary === null) {
    return (
      <PageState
        state="unavailable"
        message="该回测尚未生成完整结果，请稍后查看。"
      />
    );
  }

  return (
    <>
      <section className="backtest-detail__section" aria-labelledby="backtest-summary-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">RESULT SUMMARY</p>
            <h2 id="backtest-summary-title">回测摘要</h2>
          </div>
        </div>
        <dl className="metric-list">
          <div>
            <dt>最终权益</dt>
            <dd>{formatDecimal(summary.finalEquity)} USDT</dd>
          </div>
          <div>
            <dt>净盈亏</dt>
            <dd>{formatDecimal(summary.netPnl)} USDT</dd>
          </div>
          <div>
            <dt>最大回撤</dt>
            <dd>{formatPercent(summary.maxDrawdownFraction)}</dd>
          </div>
          <div>
            <dt>胜率</dt>
            <dd>{formatPercent(summary.winRate)}</dd>
          </div>
          <div>
            <dt>已平仓交易</dt>
            <dd>{summary.closedTradeCount}</dd>
          </div>
          <div>
            <dt>模拟成交</dt>
            <dd>{summary.fillCount}</dd>
          </div>
          <div>
            <dt>风控拒绝</dt>
            <dd>{summary.rejectionCount}</dd>
          </div>
          <div>
            <dt>收益率</dt>
            <dd>{formatPercent(summary.returnFraction)}</dd>
          </div>
        </dl>
      </section>

      <section className="backtest-detail__section" aria-labelledby="backtest-snapshot-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">SNAPSHOT METADATA</p>
            <h2 id="backtest-snapshot-title">行情快照</h2>
          </div>
        </div>
        <dl className="metadata-list">
          <div>
            <dt>已收盘 K 线数量</dt>
            <dd>{summary.candleCount}</dd>
          </div>
          <div>
            <dt>快照哈希</dt>
            <dd className="backtest-detail__hash">{summary.snapshotHash}</dd>
          </div>
        </dl>
      </section>

      <section className="backtest-detail__section" aria-labelledby="backtest-closed-trades-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">CLOSED TRADE LEDGER</p>
            <h2 id="backtest-closed-trades-title">已平仓交易</h2>
          </div>
        </div>
        {run.closedTrades.length === 0 ? (
          <PageState state="empty" message="本次回测没有已平仓交易。" />
        ) : (
          <div className="table-scroll">
            <table className="market-table" aria-label="已平仓交易">
              <thead>
                <tr>
                  <th scope="col">开仓时间（UTC）</th>
                  <th scope="col">平仓时间（UTC）</th>
                  <th scope="col">数量</th>
                  <th scope="col">净盈亏</th>
                </tr>
              </thead>
              <tbody>
                {run.closedTrades.map((trade) => (
                  <tr key={`${trade.openedAt}-${trade.closedAt}`}>
                    <td><time dateTime={trade.openedAt}>{trade.openedAt}</time></td>
                    <td><time dateTime={trade.closedAt}>{trade.closedAt}</time></td>
                    <td>{formatDecimal(trade.quantity)} BTC</td>
                    <td>{formatDecimal(trade.netPnl)} USDT</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {hasOpenPosition(summary.openPositionQuantity) ? (
        <section className="backtest-detail__section" aria-labelledby="backtest-open-position-title">
          <div className="section-heading">
            <div>
              <p className="section-kicker">MARK TO MARKET</p>
              <h2 id="backtest-open-position-title">未平仓盯市</h2>
            </div>
          </div>
          <dl className="metadata-list">
            <div>
              <dt>未平仓数量</dt>
              <dd>{formatDecimal(summary.openPositionQuantity)} BTC</dd>
            </div>
            <div>
              <dt>未实现盈亏</dt>
              <dd>{formatDecimal(summary.unrealizedPnl)} USDT</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section className="backtest-detail__section" aria-labelledby="backtest-events-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">AUDIT EVENTS</p>
            <h2 id="backtest-events-title">审计事件</h2>
          </div>
        </div>
        <div className="table-scroll">
          <table className="market-table" aria-label="回测审计事件">
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col">事件</th>
                <th scope="col">发生时间（UTC）</th>
                <th scope="col">K 线序号</th>
                <th scope="col">幂等键</th>
                <th scope="col">审计载荷</th>
              </tr>
            </thead>
            <tbody>
              {run.events.map((event) => (
                <tr key={event.sequence}>
                  <td>{event.sequence}</td>
                  <td>{eventLabels[event.kind]}</td>
                  <td><time dateTime={event.occurredAt}>{event.occurredAt}</time></td>
                  <td>{event.candleSequence ?? "不适用"}</td>
                  <td>{event.idempotencyKey ?? "不适用"}</td>
                  <td><code>{JSON.stringify(event.payload)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function BacktestDetailContent({ backtestId }: { backtestId: string }) {
  const api = useWorkbenchApi();
  const runQuery = useQuery({
    queryKey: ["backtest", backtestId],
    queryFn: () => api.getBacktest(backtestId),
  });

  if (runQuery.isPending) {
    return <PageState state="loading" />;
  }
  if (runQuery.isError) {
    return (
      <PageState
        state="error"
        message="无法读取回测详情，请稍后重试。"
      />
    );
  }
  if (runQuery.data === undefined) {
    return (
      <PageState
        state="unavailable"
        message="回测详情暂不可用，请稍后重试。"
      />
    );
  }

  const run = runQuery.data;
  return (
    <section className="research-page backtest-detail">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">不可变历史模拟记录</p>
          <h1>回测详情</h1>
          <p>
            运行状态：{statusLabels[run.status]}。所有结果均来自历史模拟，不连接交易所或真实账户。
          </p>
        </div>
        <Link className="text-link" to="/backtests">返回策略回测</Link>
      </header>

      <section className="backtest-detail__section" aria-labelledby="backtest-config-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">FROZEN CONFIGURATION</p>
            <h2 id="backtest-config-title">回测运行配置</h2>
          </div>
        </div>
        <dl className="metadata-list">
          <div><dt>回测运行 ID</dt><dd>{run.id}</dd></div>
          <div><dt>标的与周期</dt><dd>{run.symbol} · {run.timeframe}</dd></div>
          <div><dt>开始时间（UTC）</dt><dd><time dateTime={run.startAt}>{run.startAt}</time></dd></div>
          <div><dt>结束时间（UTC）</dt><dd><time dateTime={run.endAt}>{run.endAt}</time></dd></div>
          <div><dt>初始资金</dt><dd>{formatDecimal(run.initialCash)} USDT</dd></div>
          <div><dt>策略</dt><dd>{run.strategyId} · {run.strategyVersion}</dd></div>
          <div><dt>手续费 / 滑点</dt><dd>{formatPercent(run.executionConfig.feeRate)} / {formatPercent(run.executionConfig.slippageRate)}</dd></div>
          <div><dt>最大回撤限制</dt><dd>{formatPercent(run.riskConfig.maxDrawdownFraction)}</dd></div>
          <div><dt>创建时间（UTC）</dt><dd><time dateTime={run.createdAt}>{run.createdAt}</time></dd></div>
        </dl>
      </section>

      <BacktestResult run={run} />
      <p className="backtest-disclaimer">历史模拟，不等同于模拟盘或实盘</p>
    </section>
  );
}

export function BacktestDetailPage() {
  const { backtestId } = useParams();
  if (backtestId === undefined) {
    return (
      <PageState
        state="unavailable"
        message="未提供可读取的回测运行标识。"
      />
    );
  }
  return <BacktestDetailContent key={backtestId} backtestId={backtestId} />;
}
