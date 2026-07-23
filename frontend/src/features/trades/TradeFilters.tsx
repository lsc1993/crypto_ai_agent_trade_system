import { useState, type FormEvent } from "react";

import {
  tradeFiltersSchema,
  type TradeFilters as TradeFilterValues,
} from "../../domain/trade";

interface TradeFiltersProps {
  initialFilters: TradeFilterValues;
  onApply: (filters: TradeFilterValues) => void;
}

function optionalValue(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length === 0 ? undefined : trimmed;
}

export function TradeFilters({
  initialFilters,
  onApply,
}: TradeFiltersProps) {
  const [symbol, setSymbol] = useState(initialFilters.symbol ?? "");
  const [direction, setDirection] = useState(
    initialFilters.direction ?? "",
  );
  const [horizon, setHorizon] = useState(initialFilters.horizon ?? "");
  const [status, setStatus] = useState(initialFilters.status ?? "");
  const [label, setLabel] = useState(initialFilters.label ?? "");
  const [from, setFrom] = useState(initialFilters.from ?? "");
  const [to, setTo] = useState(initialFilters.to ?? "");
  const [error, setError] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = tradeFiltersSchema.safeParse({
      symbol: optionalValue(symbol),
      direction: optionalValue(direction),
      horizon: optionalValue(horizon),
      status: optionalValue(status),
      label: optionalValue(label),
      from: optionalValue(from),
      to: optionalValue(to),
      page: 1,
      pageSize: initialFilters.pageSize ?? 20,
    });
    if (!result.success) {
      setError(true);
      return;
    }
    setError(false);
    onApply(result.data);
  }

  return (
    <form className="research-panel" onSubmit={handleSubmit}>
      <h2>筛选交易日志</h2>
      <label>
        <span>标的</span>
        <select
          value={symbol}
          onChange={(event) => {
            setSymbol(event.target.value);
          }}
        >
          <option value="">全部</option>
          <option value="BTCUSDT">BTCUSDT</option>
          <option value="ETHUSDT">ETHUSDT</option>
        </select>
      </label>
      <label>
        <span>方向</span>
        <select
          value={direction}
          onChange={(event) => {
            setDirection(event.target.value);
          }}
        >
          <option value="">全部</option>
          <option value="long">多向研究</option>
          <option value="short">空向研究</option>
        </select>
      </label>
      <label>
        <span>持有周期</span>
        <select
          value={horizon}
          onChange={(event) => {
            setHorizon(event.target.value);
          }}
        >
          <option value="">全部</option>
          <option value="short_term">短期</option>
          <option value="medium_term">中期</option>
        </select>
      </label>
      <label>
        <span>状态</span>
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
          }}
        >
          <option value="">全部</option>
          <option value="open">记录中</option>
          <option value="closed">已结束</option>
        </select>
      </label>
      <label>
        <span>标签</span>
        <input
          value={label}
          onChange={(event) => {
            setLabel(event.target.value);
          }}
        />
      </label>
      <label>
        <span>开始时间（UTC）</span>
        <input
          value={from}
          placeholder="2025-01-01T00:00:00Z"
          onChange={(event) => {
            setFrom(event.target.value);
          }}
        />
      </label>
      <label>
        <span>结束时间（UTC）</span>
        <input
          value={to}
          placeholder="2025-01-31T23:59:59Z"
          onChange={(event) => {
            setTo(event.target.value);
          }}
        />
      </label>
      <button className="primary-action" type="submit">
        应用筛选
      </button>
      {error ? (
        <p className="inline-error" role="alert">
          筛选条件无效，请检查 UTC 时间与可选值。
        </p>
      ) : null}
    </form>
  );
}
