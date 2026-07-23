import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { useWorkbenchApi } from "../../app/providers";
import { PageState } from "../../components/common/PageState";
import {
  identifierSchema,
  pageSchema,
} from "../../domain/primitives";
import {
  tradeDraftSchema,
  tradeSchema,
  type TradeDraft,
} from "../../domain/trade";
import { TradeForm } from "./TradeForm";

type LinkedReportResult =
  | { valid: true; linkedReportId: string | null }
  | { valid: false; linkedReportId: null };

function parseLinkedReportId(
  searchParams: URLSearchParams,
): LinkedReportResult {
  const values = searchParams.getAll("linkedAnalysisReportId");
  if (values.length === 0) {
    return { valid: true, linkedReportId: null };
  }
  if (values.length !== 1) {
    return { valid: false, linkedReportId: null };
  }
  const result = identifierSchema.safeParse(values[0]);
  return result.success
    ? { valid: true, linkedReportId: result.data }
    : { valid: false, linkedReportId: null };
}

function newTradeDraft(linkedReportId: string | null): TradeDraft {
  return tradeDraftSchema.parse({
    symbol: "BTCUSDT",
    direction: "long",
    horizon: "short_term",
    labels: [],
    linkedReportId,
    leverage: "1",
    legs: [
      {
        id: "leg-new-1",
        action: "open",
        executedAt: "2025-01-01T00:00:00Z",
        price: "1",
        quantity: "1",
        fee: "0",
      },
    ],
    fundingFee: "0",
    thesis: "",
    review: "",
  });
}

export function TradeEditorPage() {
  const api = useWorkbenchApi();
  const { tradeId } = useParams();
  const [searchParams] = useSearchParams();
  const linkedReport = useMemo(
    () => parseLinkedReportId(searchParams),
    [searchParams],
  );
  const parsedTradeId =
    tradeId === undefined
      ? null
      : identifierSchema.safeParse(tradeId);
  const isEdit = tradeId !== undefined;
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const tradeLookup = useQuery({
    queryKey: [
      "trade-edit-lookup",
      parsedTradeId?.success === true ? parsedTradeId.data : null,
    ],
    enabled: isEdit && parsedTradeId?.success === true,
    queryFn: async () => {
      const response = await api.listTrades({
        page: 1,
        pageSize: 100,
      });
      return pageSchema(tradeSchema).parse(response);
    },
  });
  const saveMutation = useMutation({
    mutationKey: ["save-trade-journal", tradeId],
    mutationFn: async (draft: TradeDraft) => {
      const parsedDraft = tradeDraftSchema.parse(draft);
      if (parsedTradeId !== null && parsedTradeId.success) {
        return tradeSchema.parse(
          await api.updateTrade(parsedTradeId.data, parsedDraft),
        );
      }
      return tradeSchema.parse(await api.createTrade(parsedDraft));
    },
  });

  if (isEdit && (parsedTradeId === null || !parsedTradeId.success)) {
    return (
      <PageState
        state="unavailable"
        message="交易日志 ID 无效，无法编辑。"
      />
    );
  }

  if (isEdit && tradeLookup.isPending) {
    return <PageState state="loading" />;
  }

  if (isEdit && tradeLookup.isError) {
    return (
      <PageState state="error" message="无法读取待编辑的交易日志。" />
    );
  }

  const existing =
    isEdit && tradeLookup.data !== undefined
      ? tradeLookup.data.items.find((trade) => trade.id === tradeId)
      : undefined;
  if (isEdit && existing === undefined) {
    return (
      <PageState
        state="unavailable"
        message="未找到指定的交易日志。"
      />
    );
  }

  const initialDraft =
    existing === undefined
      ? newTradeDraft(linkedReport.linkedReportId)
      : tradeDraftSchema.parse(existing);

  async function handleSubmit(draft: TradeDraft) {
    setSaved(false);
    setSaveError(false);
    try {
      await saveMutation.mutateAsync(draft);
      setSaved(true);
    } catch {
      setSaveError(true);
    }
  }

  return (
    <section className="research-page">
      <header className="research-page__heading">
        <div>
          <p className="route-page__kicker">模拟研究日志</p>
          <h1>{isEdit ? "编辑交易日志" : "新增交易日志"}</h1>
          <p>
            仅记录人工研究过程与复盘，不连接账户，也不触发任何交易执行。
          </p>
        </div>
      </header>
      {!linkedReport.valid ? (
        <p className="inline-error" role="alert">
          关联分析报告参数无效，已安全忽略。
        </p>
      ) : null}
      <TradeForm
        key={
          existing?.id ??
          `new:${linkedReport.linkedReportId ?? "unlinked"}`
        }
        initialDraft={initialDraft}
        submitLabel="保存交易日志"
        onSubmit={handleSubmit}
      />
      {saved ? <p role="status">交易日志已保存。</p> : null}
      {saveError ? (
        <p className="inline-error" role="alert">
          交易日志保存失败，请稍后重试。
        </p>
      ) : null}
    </section>
  );
}
