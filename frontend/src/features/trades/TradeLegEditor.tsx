import {
  tradeLegActionSchema,
  type TradeLeg,
} from "../../domain/trade";

interface TradeLegEditorProps {
  index: number;
  leg: TradeLeg;
  canRemove: boolean;
  onChange: (leg: TradeLeg) => void;
  onRemove: () => void;
}

export function TradeLegEditor({
  index,
  leg,
  canRemove,
  onChange,
  onRemove,
}: TradeLegEditorProps) {
  const number = index + 1;

  return (
    <fieldset className="research-panel">
      <legend>交易腿 {number}</legend>
      <label>
        <span>交易腿 ID</span>
        <input
          value={leg.id}
          onChange={(event) => {
            onChange({ ...leg, id: event.target.value });
          }}
        />
      </label>
      <label>
        <span>动作</span>
        <select
          value={leg.action}
          onChange={(event) => {
            const result = tradeLegActionSchema.safeParse(
              event.target.value,
            );
            if (result.success) {
              onChange({ ...leg, action: result.data });
            }
          }}
        >
          <option value="open">增加仓位记录</option>
          <option value="reduce">减少仓位记录</option>
          <option value="close">结束仓位记录</option>
        </select>
      </label>
      <label>
        <span>执行时间（UTC）</span>
        <input
          value={leg.executedAt}
          placeholder="2025-01-01T00:00:00Z"
          onChange={(event) => {
            onChange({ ...leg, executedAt: event.target.value });
          }}
        />
      </label>
      <label>
        <span>价格</span>
        <input
          inputMode="decimal"
          value={leg.price}
          onChange={(event) => {
            onChange({ ...leg, price: event.target.value });
          }}
        />
      </label>
      <label>
        <span>数量</span>
        <input
          inputMode="decimal"
          value={leg.quantity}
          onChange={(event) => {
            onChange({ ...leg, quantity: event.target.value });
          }}
        />
      </label>
      <label>
        <span>手续费</span>
        <input
          inputMode="decimal"
          value={leg.fee}
          onChange={(event) => {
            onChange({ ...leg, fee: event.target.value });
          }}
        />
      </label>
      {canRemove ? (
        <button className="secondary-action" type="button" onClick={onRemove}>
          移除交易腿 {number}
        </button>
      ) : null}
    </fieldset>
  );
}
