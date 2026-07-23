import Decimal from "decimal.js";
import { useMemo, useRef, useState, type FormEvent } from "react";
import { z } from "zod";

import { symbolSchema } from "../../domain/primitives";
import {
  tradeDirectionSchema,
  tradeDraftSchema,
  tradeHorizonSchema,
  type TradeDraft,
  type TradeLeg,
} from "../../domain/trade";
import { parseTradeFormDraft } from "./trade-form-schema";
import { TradeLegEditor } from "./TradeLegEditor";

interface TradeFormProps {
  initialDraft: TradeDraft;
  submitLabel: string;
  onSubmit: (draft: TradeDraft) => void | Promise<void>;
}

function validationMessage(error: unknown): string {
  if (!(error instanceof z.ZodError)) {
    return "交易日志内容无效，请检查后重试。";
  }
  const messages = error.issues.map((issue) => issue.message);
  if (
    messages.some((message) =>
      message.includes("cannot exceed opened quantity"),
    )
  ) {
    return "减仓或平仓数量不能超过累计开仓数量。";
  }
  if (
    messages.some((message) =>
      message.includes("must leave quantity open"),
    )
  ) {
    return "减仓后必须保留剩余数量。";
  }
  if (
    messages.some((message) =>
      message.includes("must exactly clear"),
    )
  ) {
    return "平仓数量必须恰好清空剩余数量。";
  }
  if (messages.some((message) => message.includes("unique"))) {
    return "交易腿 ID 必须唯一。";
  }
  if (messages.some((message) => message.includes("UTC"))) {
    return "执行时间必须是以 Z 结尾的 UTC RFC 3339 时间。";
  }
  return "金额、价格与数量必须使用规范十进制字符串。";
}

function nominalValuePreview(draft: TradeDraft): string {
  try {
    return draft.legs
      .reduce(
        (total, leg) =>
          total.plus(new Decimal(leg.price).times(leg.quantity)),
        new Decimal(0),
      )
      .toString();
  } catch {
    return "—";
  }
}

export function TradeForm({
  initialDraft,
  submitLabel,
  onSubmit,
}: TradeFormProps) {
  const [draft, setDraft] = useState(() =>
    tradeDraftSchema.parse(initialDraft),
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const nextLegSequence = useRef(1);
  const preview = useMemo(() => nominalValuePreview(draft), [draft]);

  function updateLeg(index: number, leg: TradeLeg) {
    setDraft((current) => ({
      ...current,
      legs: current.legs.map((candidate, candidateIndex) =>
        candidateIndex === index ? leg : candidate,
      ),
    }));
  }

  function addLeg() {
    setDraft((current) => {
      const previous = current.legs.at(-1);
      let id = "";
      do {
        id = `leg-added-${nextLegSequence.current}`;
        nextLegSequence.current += 1;
      } while (current.legs.some((leg) => leg.id === id));
      const leg: TradeLeg = {
        id,
        action: "reduce",
        executedAt:
          previous?.executedAt ?? "2025-01-01T00:00:00Z",
        price: previous?.price ?? "1",
        quantity: previous?.quantity ?? "1",
        fee: "0",
      };
      return { ...current, legs: [...current.legs, leg] };
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let parsed: TradeDraft;
    try {
      parsed = parseTradeFormDraft(draft);
    } catch (caught) {
      setError(validationMessage(caught));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(parsed);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="research-page"
      onSubmit={(event) => {
        void handleSubmit(event);
      }}
    >
      <section className="research-panel">
        <h2>日志信息</h2>
        <label>
          <span>标的</span>
          <select
            value={draft.symbol}
            onChange={(event) => {
              const result = symbolSchema.safeParse(event.target.value);
              if (result.success) {
                setDraft((current) => ({
                  ...current,
                  symbol: result.data,
                }));
              }
            }}
          >
            <option value="BTCUSDT">BTCUSDT</option>
            <option value="ETHUSDT">ETHUSDT</option>
          </select>
        </label>
        <label>
          <span>方向</span>
          <select
            value={draft.direction}
            onChange={(event) => {
              const result = tradeDirectionSchema.safeParse(
                event.target.value,
              );
              if (result.success) {
                setDraft((current) => ({
                  ...current,
                  direction: result.data,
                }));
              }
            }}
          >
            <option value="long">多向研究</option>
            <option value="short">空向研究</option>
          </select>
        </label>
        <label>
          <span>持有周期</span>
          <select
            value={draft.horizon}
            onChange={(event) => {
              const result = tradeHorizonSchema.safeParse(
                event.target.value,
              );
              if (result.success) {
                setDraft((current) => ({
                  ...current,
                  horizon: result.data,
                }));
              }
            }}
          >
            <option value="short_term">短期</option>
            <option value="medium_term">中期</option>
          </select>
        </label>
        <label>
          <span>标签</span>
          <input
            value={draft.labels.join(", ")}
            onChange={(event) => {
              const labels = event.target.value
                .split(",")
                .map((label) => label.trim())
                .filter((label) => label.length > 0);
              setDraft((current) => ({ ...current, labels }));
            }}
          />
        </label>
        <label>
          <span>关联分析报告 ID</span>
          <input
            value={draft.linkedReportId ?? ""}
            onChange={(event) => {
              const value = event.target.value.trim();
              setDraft((current) => ({
                ...current,
                linkedReportId: value.length === 0 ? null : value,
              }));
            }}
          />
        </label>
        <label>
          <span>杠杆</span>
          <input
            inputMode="decimal"
            value={draft.leverage}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                leverage: event.target.value,
              }));
            }}
          />
        </label>
        <label>
          <span>资金费</span>
          <input
            inputMode="decimal"
            value={draft.fundingFee}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                fundingFee: event.target.value,
              }));
            }}
          />
        </label>
        <label>
          <span>研究理由</span>
          <textarea
            value={draft.thesis}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                thesis: event.target.value,
              }));
            }}
          />
        </label>
        <label>
          <span>复盘记录</span>
          <textarea
            value={draft.review}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                review: event.target.value,
              }));
            }}
          />
        </label>
      </section>

      <section aria-labelledby="trade-legs-title">
        <h2 id="trade-legs-title">交易腿记录</h2>
        <p>客户端校验仅用于即时提示；后端服务仍是最终权威。</p>
        {draft.legs.map((leg, index) => (
          <TradeLegEditor
            key={index}
            index={index}
            leg={leg}
            canRemove={draft.legs.length > 1}
            onChange={(updated) => {
              updateLeg(index, updated);
            }}
            onRemove={() => {
              setDraft((current) => ({
                ...current,
                legs: current.legs.filter(
                  (_, candidateIndex) => candidateIndex !== index,
                ),
              }));
            }}
          />
        ))}
        <button className="secondary-action" type="button" onClick={addLeg}>
          添加交易腿
        </button>
      </section>

      <p role="status">名义价值预览：{preview} USDT</p>
      {error !== null ? (
        <p className="inline-error" role="alert">
          {error}
        </p>
      ) : null}
      <button
        className="primary-action"
        type="submit"
        disabled={submitting}
      >
        {submitLabel}
      </button>
    </form>
  );
}
