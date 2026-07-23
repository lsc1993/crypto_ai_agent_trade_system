import { useState, type FormEvent } from "react";

import {
  analyticsFiltersSchema,
  type AnalyticsFilters,
} from "../../domain/analytics";

interface AnalyticsFiltersProps {
  value: AnalyticsFilters;
  onApply: (filters: AnalyticsFilters) => void;
}

interface FilterFormValues {
  symbol: string;
  direction: string;
  horizon: string;
  label: string;
  from: string;
  to: string;
}

const utcValidationMessage = "筛选时间必须使用 UTC RFC3339 Z 格式。";

function createFormValues(filters: AnalyticsFilters): FilterFormValues {
  return {
    symbol: filters.symbol ?? "",
    direction: filters.direction ?? "",
    horizon: filters.horizon ?? "",
    label: filters.label ?? "",
    from: filters.from ?? "",
    to: filters.to ?? "",
  };
}

function optionalValue(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

function parseFilterValues(values: FilterFormValues): AnalyticsFilters | null {
  const symbol = optionalValue(values.symbol);
  const direction = optionalValue(values.direction);
  const horizon = optionalValue(values.horizon);
  const label = optionalValue(values.label);
  const from = optionalValue(values.from);
  const to = optionalValue(values.to);
  const result = analyticsFiltersSchema.safeParse({
    ...(symbol === undefined ? {} : { symbol }),
    ...(direction === undefined ? {} : { direction }),
    ...(horizon === undefined ? {} : { horizon }),
    ...(label === undefined ? {} : { label }),
    ...(from === undefined ? {} : { from }),
    ...(to === undefined ? {} : { to }),
  });

  return result.success ? result.data : null;
}

export function AnalyticsFiltersPanel({
  value,
  onApply,
}: AnalyticsFiltersProps) {
  const [formValues, setFormValues] = useState(() => createFormValues(value));
  const [validationMessage, setValidationMessage] = useState<string | null>(
    null,
  );

  function updateField<Key extends keyof FilterFormValues>(
    key: Key,
    nextValue: FilterFormValues[Key],
  ) {
    setFormValues((current) => ({ ...current, [key]: nextValue }));
    setValidationMessage(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseFilterValues(formValues);
    if (parsed === null) {
      setValidationMessage(utcValidationMessage);
      return;
    }

    setValidationMessage(null);
    onApply(parsed);
  }

  return (
    <form
      aria-label="复盘筛选"
      className="research-panel analytics-filters"
      onSubmit={handleSubmit}
    >
      <h2>筛选复盘统计</h2>
      <div className="analytics-filters__fields">
        <label>
          <span>标的</span>
          <select
            value={formValues.symbol}
            onChange={(event) => {
              updateField("symbol", event.target.value);
            }}
          >
            <option value="">全部标的</option>
            <option value="BTCUSDT">BTCUSDT</option>
            <option value="ETHUSDT">ETHUSDT</option>
          </select>
        </label>

        <label>
          <span>方向</span>
          <select
            value={formValues.direction}
            onChange={(event) => {
              updateField("direction", event.target.value);
            }}
          >
            <option value="">全部方向</option>
            <option value="long">多头</option>
            <option value="short">空头</option>
          </select>
        </label>

        <label>
          <span>周期</span>
          <select
            value={formValues.horizon}
            onChange={(event) => {
              updateField("horizon", event.target.value);
            }}
          >
            <option value="">全部周期</option>
            <option value="short_term">短期</option>
            <option value="medium_term">中期</option>
          </select>
        </label>

        <label>
          <span>标签</span>
          <input
            value={formValues.label}
            onChange={(event) => {
              updateField("label", event.target.value);
            }}
          />
        </label>

        <label>
          <span>开始时间（UTC）</span>
          <input
            placeholder="2025-01-01T00:00:00Z"
            value={formValues.from}
            onChange={(event) => {
              updateField("from", event.target.value);
            }}
          />
        </label>

        <label>
          <span>结束时间（UTC）</span>
          <input
            placeholder="2025-01-31T23:59:59Z"
            value={formValues.to}
            onChange={(event) => {
              updateField("to", event.target.value);
            }}
          />
        </label>
      </div>
      <button className="primary-action" type="submit">
        应用筛选条件
      </button>
      {validationMessage !== null ? (
        <p className="inline-error" role="alert">
          {validationMessage}
        </p>
      ) : null}
    </form>
  );
}
