import {
  analysisStreamEventSchema,
  type AnalysisStreamEvent,
} from "../../domain/report";

export interface ReportEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(): void;
}

export type ReportEventSourceFactory = (url: string) => ReportEventSource;

export interface ReportStreamOptions {
  url: string;
  onEvent: (event: AnalysisStreamEvent) => void;
  eventSourceFactory?: ReportEventSourceFactory;
}

function defaultEventSourceFactory(url: string): ReportEventSource {
  return new EventSource(url);
}

export function subscribeToReportStream(
  options: ReportStreamOptions,
): () => void {
  const url = new URL(options.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Report stream URL must use HTTP(S)");
  }
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
