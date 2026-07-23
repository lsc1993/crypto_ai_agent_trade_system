import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useWorkbenchApi } from "../../app/providers";
import type { Symbol } from "../../domain/primitives";
import type {
  AnalysisStreamEvent,
  ReportStatus,
} from "../../domain/report";

const statusLabels: Record<ReportStatus, string> = {
  queued: "排队中",
  running: "分析中",
  completed: "已完成",
  degraded: "已降级",
  failed: "失败",
};

export interface ReportGeneratorProps {
  symbol: Symbol;
}

export function ReportGenerator({ symbol }: ReportGeneratorProps) {
  const api = useWorkbenchApi();
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [event, setEvent] = useState<AnalysisStreamEvent | null>(null);
  const startMutation = useMutation({
    mutationKey: ["start-report", symbol],
    mutationFn: () => api.startReport({ symbol }),
    onSuccess: ({ analysisId: freshAnalysisId }) => {
      unsubscribeRef.current?.();
      setAnalysisId(freshAnalysisId);
      setEvent(null);
      unsubscribeRef.current = api.subscribeReport(
        freshAnalysisId,
        setEvent,
      );
    },
  });

  useEffect(
    () => () => {
      unsubscribeRef.current?.();
    },
    [],
  );

  return (
    <section
      className="report-generator"
      aria-labelledby={`report-generator-${symbol}`}
    >
      <div>
        <h2 id={`report-generator-${symbol}`}>生成研究报告</h2>
        <p>
          为 {symbol} 创建新的只读分析任务。结果仅表达观察、推断、风险和限制。
        </p>
      </div>
      <button
        className="primary-action"
        type="button"
        disabled={startMutation.isPending}
        onClick={() => {
          startMutation.mutate();
        }}
      >
        生成 AI 研究报告
      </button>
      {startMutation.isPending ? (
        <p role="status">正在创建研究任务。</p>
      ) : null}
      {startMutation.isError ? (
        <p className="inline-error" role="alert">
          研究任务创建失败，请稍后重试。
        </p>
      ) : null}
      {analysisId !== null ? (
        <p className="report-generator__analysis">
          新分析 ID：{analysisId}
        </p>
      ) : null}
      {event !== null ? (
        <p className="report-generator__lifecycle" role="status">
          {statusLabels[event.status]} · {event.occurredAt}
        </p>
      ) : null}
    </section>
  );
}
