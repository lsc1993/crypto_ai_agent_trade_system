import { useMutation } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

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

function isTerminalStatus(status: ReportStatus): boolean {
  return (
    status === "completed" ||
    status === "degraded" ||
    status === "failed"
  );
}

export interface ReportGeneratorProps {
  symbol: Symbol;
}

export function ReportGenerator({ symbol }: ReportGeneratorProps) {
  const api = useWorkbenchApi();
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const activeAnalysisIdRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  const requestEpochRef = useRef(0);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [event, setEvent] = useState<AnalysisStreamEvent | null>(null);
  const clearSubscription = useCallback(() => {
    const unsubscribe = unsubscribeRef.current;
    unsubscribeRef.current = null;
    activeAnalysisIdRef.current = null;
    unsubscribe?.();
  }, []);
  const startMutation = useMutation({
    mutationKey: ["start-report", symbol],
    mutationFn: (requestEpoch: number) => {
      void requestEpoch;
      return api.startReport({ symbol });
    },
    onSuccess: ({ analysisId: freshAnalysisId }, requestEpoch) => {
      if (
        !mountedRef.current ||
        requestEpochRef.current !== requestEpoch
      ) {
        return;
      }
      clearSubscription();
      setAnalysisId(freshAnalysisId);
      setEvent(null);
      activeAnalysisIdRef.current = freshAnalysisId;
      const unsubscribe = api.subscribeReport(
        freshAnalysisId,
        (nextEvent) => {
          if (activeAnalysisIdRef.current !== freshAnalysisId) {
            return;
          }
          setEvent(nextEvent);
          if (isTerminalStatus(nextEvent.status)) {
            clearSubscription();
          }
        },
      );
      if (activeAnalysisIdRef.current === freshAnalysisId) {
        unsubscribeRef.current = unsubscribe;
      } else {
        unsubscribe();
      }
    },
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestEpochRef.current += 1;
      clearSubscription();
    };
  }, [clearSubscription]);

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
          requestEpochRef.current += 1;
          startMutation.mutate(requestEpochRef.current);
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
