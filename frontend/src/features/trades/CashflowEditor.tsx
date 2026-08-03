import type { TradeCashflow } from "../../domain/trade";

interface CashflowEditorProps {
  cashflow: TradeCashflow;
  index: number;
  onChange: (cashflow: TradeCashflow) => void;
  onRemove: () => void;
}

export function CashflowEditor({
  cashflow,
  index,
  onChange,
  onRemove,
}: CashflowEditorProps) {
  const number = index + 1;

  return (
    <fieldset className="research-panel">
      <legend>资金现金流 {number}</legend>
      <label>
        <span>发生时间（UTC）</span>
        <input
          value={cashflow.occurredAt}
          placeholder="2025-01-01T00:00:00Z"
          onChange={(event) => {
            onChange({ ...cashflow, occurredAt: event.target.value });
          }}
        />
      </label>
      <label>
        <span>资金现金流</span>
        <input
          inputMode="decimal"
          value={cashflow.amount}
          onChange={(event) => {
            onChange({ ...cashflow, amount: event.target.value });
          }}
        />
      </label>
      <label>
        <span>说明</span>
        <input
          value={cashflow.reason}
          onChange={(event) => {
            onChange({ ...cashflow, reason: event.target.value });
          }}
        />
      </label>
      <button className="secondary-action" type="button" onClick={onRemove}>
        移除资金现金流 {number}
      </button>
    </fieldset>
  );
}
