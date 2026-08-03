import { useState, type FormEvent } from "react";

import type { BacktestRequest } from "../../domain/backtest";
import {
  defaultBacktestFormValues,
  parseBacktestForm,
  type BacktestFormValues,
} from "./backtest-form-schema";

interface BacktestFormProps {
  isSubmitting: boolean;
  submissionFailed: boolean;
  onSubmit: (input: BacktestRequest) => void;
}

export function BacktestForm({
  isSubmitting,
  submissionFailed,
  onSubmit,
}: BacktestFormProps) {
  const [values, setValues] = useState<BacktestFormValues>(
    defaultBacktestFormValues,
  );
  const [validationMessage, setValidationMessage] = useState<string | null>(
    null,
  );

  function updateField<K extends keyof BacktestFormValues>(
    field: K,
    value: BacktestFormValues[K],
  ) {
    setValues((current) => ({ ...current, [field]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseBacktestForm(values);
    if (parsed.input === null) {
      setValidationMessage(parsed.message);
      return;
    }

    setValidationMessage(null);
    onSubmit(parsed.input);
  }

  return (
    <form
      className="backtest-form"
      aria-label="历史回测配置"
      onSubmit={handleSubmit}
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">DETERMINISTIC REPLAY</p>
          <h2>运行历史回测</h2>
        </div>
      </div>
      <p className="backtest-form__intro">
        仅重放已收盘的 BTCUSDT 1 小时 K 线；该功能不连接交易所、账户或任何执行服务。
      </p>
      <div className="backtest-form__fields">
        <label>
          开始时间（UTC）
          <input
            name="startAt"
            value={values.startAt}
            onChange={(event) => updateField("startAt", event.target.value)}
            placeholder="2026-06-01T00:00:00Z"
            spellCheck={false}
          />
        </label>
        <label>
          结束时间（UTC）
          <input
            name="endAt"
            value={values.endAt}
            onChange={(event) => updateField("endAt", event.target.value)}
            placeholder="2026-07-01T00:00:00Z"
            spellCheck={false}
          />
        </label>
        <label>
          初始资金（USDT）
          <input
            name="initialCash"
            value={values.initialCash}
            onChange={(event) =>
              updateField("initialCash", event.target.value)
            }
            inputMode="decimal"
            spellCheck={false}
          />
        </label>
      </div>
      <dl className="backtest-form__assumptions">
        <div>
          <dt>策略</dt>
          <dd>SMA 20 / 50 交叉（固定）</dd>
        </div>
        <div>
          <dt>手续费</dt>
          <dd>0.10%（固定）</dd>
        </div>
        <div>
          <dt>滑点</dt>
          <dd>0.05%（固定）</dd>
        </div>
        <div>
          <dt>风控限制</dt>
          <dd>最大敞口 20%、止损 2%、最大回撤 15%</dd>
        </div>
      </dl>
      {validationMessage === null && !submissionFailed ? null : (
        <p className="backtest-form__error" role="alert">
          {validationMessage ?? "无法启动历史回测，请稍后重试。"}
        </p>
      )}
      <button
        className="primary-action"
        type="submit"
        disabled={isSubmitting}
      >
        {isSubmitting ? "正在运行历史回测" : "运行历史回测"}
      </button>
    </form>
  );
}
