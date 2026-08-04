import { useState, type FormEvent } from "react";

import type { PaperAccountCreate } from "../../domain/paper-trading";
import {
  defaultPaperAccountFormValues,
  parsePaperAccountForm,
  type PaperAccountFormValues,
} from "./paper-account-form-schema";

interface PaperAccountFormProps {
  isSubmitting: boolean;
  submissionFailed: boolean;
  onSubmit: (input: PaperAccountCreate) => void;
}

export function PaperAccountForm({
  isSubmitting,
  submissionFailed,
  onSubmit,
}: PaperAccountFormProps) {
  const [values, setValues] = useState<PaperAccountFormValues>(
    defaultPaperAccountFormValues,
  );
  const [validationMessage, setValidationMessage] = useState<string | null>(
    null,
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parsePaperAccountForm(values);
    if (parsed.input === null) {
      setValidationMessage(parsed.message);
      return;
    }

    setValidationMessage(null);
    onSubmit(parsed.input);
  }

  return (
    <form
      className="paper-account-form"
      aria-label="创建模拟盘账户"
      onSubmit={handleSubmit}
    >
      <div className="section-heading">
        <div>
          <p className="section-kicker">LOCAL PAPER ACCOUNT</p>
          <h2>创建模拟盘</h2>
        </div>
      </div>
      <p>
        账户只保存本地模拟盘余额和可审计记录；不会连接交易所私有接口、真实账户或真实订单。
      </p>
      <label>
        初始资金（USDT）
        <input
          name="initialCash"
          value={values.initialCash}
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              initialCash: event.target.value,
            }))
          }
          inputMode="decimal"
          spellCheck={false}
        />
      </label>
      {validationMessage === null && !submissionFailed ? null : (
        <p className="paper-account-form__error" role="alert">
          {validationMessage ?? "无法创建模拟盘，请稍后重试。"}
        </p>
      )}
      <button className="primary-action" type="submit" disabled={isSubmitting}>
        {isSubmitting ? "正在创建模拟盘" : "创建模拟盘"}
      </button>
    </form>
  );
}
