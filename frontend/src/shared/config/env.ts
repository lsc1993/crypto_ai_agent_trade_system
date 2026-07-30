import { z } from "zod";

const dataModeSchema = z.enum(["mock", "market-api", "api"]);
const marketDataSourceSchema = z.enum(["live", "research"]);
const apiBaseUrlSchema = z.url().refine(
  (value) => {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  },
  { message: "VITE_API_BASE_URL must use HTTP or HTTPS" },
);

export type DataMode = z.infer<typeof dataModeSchema>;
export type MarketDataSource = z.infer<typeof marketDataSourceSchema>;

export interface WorkbenchEnvironment {
  VITE_API_BASE_URL?: string | undefined;
  VITE_DATA_MODE?: string | undefined;
  VITE_MARKET_DATA_SOURCE?: string | undefined;
}

export interface WorkbenchConfig {
  apiBaseUrl: string;
  dataMode: DataMode;
  marketDataSource: MarketDataSource;
}

export class WorkbenchConfigurationError extends Error {
  readonly code:
    | "INVALID_DATA_MODE"
    | "INVALID_API_BASE_URL"
    | "INVALID_MARKET_DATA_SOURCE";

  constructor(
    code:
      | "INVALID_DATA_MODE"
      | "INVALID_API_BASE_URL"
      | "INVALID_MARKET_DATA_SOURCE",
    message: string,
  ) {
    super(message);
    this.name = "WorkbenchConfigurationError";
    this.code = code;
  }
}

export function parseWorkbenchConfig(
  value: unknown,
): WorkbenchConfig {
  const environment = z
    .object({
      VITE_API_BASE_URL: z.unknown().optional(),
      VITE_DATA_MODE: z.unknown().optional(),
      VITE_MARKET_DATA_SOURCE: z.unknown().optional(),
    })
    .parse(value);
  const mode = dataModeSchema.safeParse(environment.VITE_DATA_MODE);
  if (!mode.success) {
    throw new WorkbenchConfigurationError(
      "INVALID_DATA_MODE",
      "VITE_DATA_MODE must be mock, market-api, or api",
    );
  }

  const baseUrl = apiBaseUrlSchema.safeParse(
    environment.VITE_API_BASE_URL,
  );
  if (!baseUrl.success) {
    throw new WorkbenchConfigurationError(
      "INVALID_API_BASE_URL",
      "VITE_API_BASE_URL must be a valid HTTP(S) URL",
    );
  }

  const marketDataSource = marketDataSourceSchema.safeParse(
    environment.VITE_MARKET_DATA_SOURCE ?? "live",
  );
  if (!marketDataSource.success) {
    throw new WorkbenchConfigurationError(
      "INVALID_MARKET_DATA_SOURCE",
      "VITE_MARKET_DATA_SOURCE must be live or research",
    );
  }

  return {
    apiBaseUrl: baseUrl.data,
    dataMode: mode.data,
    marketDataSource: marketDataSource.data,
  };
}
