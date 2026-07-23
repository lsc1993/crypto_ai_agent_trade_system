import {
  analysisStreamEventSchema,
  type AnalysisStreamEvent,
} from "../../domain/report";
import { identifierSchema } from "../../domain/primitives";

export interface ReportEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(): void;
}

export type ReportEventSourceFactory = (url: string) => ReportEventSource;

export interface ReportStreamOptions {
  baseUrl: string;
  analysisId: string;
  onEvent: (event: AnalysisStreamEvent) => void;
  eventSourceFactory?: ReportEventSourceFactory;
}

function defaultEventSourceFactory(url: string): ReportEventSource {
  return new EventSource(url);
}

export function subscribeToReportStream(
  options: ReportStreamOptions,
): () => void {
  const analysisId = identifierSchema.parse(options.analysisId);
  const url = new URL(
    `/api/v1/reports/streams/${encodeURIComponent(analysisId)}`,
    options.baseUrl,
  );
  const createEventSource =
    options.eventSourceFactory ?? defaultEventSourceFactory;
  const eventSource = createEventSource(url.toString());

  eventSource.onmessage = (message) => {
    let body: unknown;
    try {
      body = JSON.parse(message.data);
    } catch {
      eventSource.close();
      return;
    }
    const parsed = analysisStreamEventSchema.safeParse(body);
    if (!parsed.success) {
      eventSource.close();
      return;
    }
    options.onEvent(parsed.data);
  };

  eventSource.onerror = () => {
    eventSource.close();
  };

  return () => {
    eventSource.close();
  };
}
