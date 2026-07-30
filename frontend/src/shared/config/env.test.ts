import { describe, expect, it } from "vitest";

import {
  parseWorkbenchConfig,
  WorkbenchConfigurationError,
} from "./env";

describe("parseWorkbenchConfig", () => {
  it("defaults the market data source to live", () => {
    expect(
      parseWorkbenchConfig({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: "market-api",
      }),
    ).toMatchObject({ marketDataSource: "live" });
  });

  it("rejects an unsupported market data source with a typed error", () => {
    expect(() =>
      parseWorkbenchConfig({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: "market-api",
        VITE_MARKET_DATA_SOURCE: "fallback",
      }),
    ).toThrowError(
      expect.objectContaining<Partial<WorkbenchConfigurationError>>({
        code: "INVALID_MARKET_DATA_SOURCE",
      }),
    );
  });
});
