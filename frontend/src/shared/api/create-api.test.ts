import { describe, expect, it, vi } from "vitest";

import { createWorkbenchApi } from "./create-api";
import { HttpWorkbenchApi } from "./http-workbench-api";
import { MockWorkbenchApi } from "./mock-workbench-api";
import { WorkbenchConfigurationError } from "../config/env";

describe("createWorkbenchApi", () => {
  it("selects the deterministic Mock implementation", () => {
    const api = createWorkbenchApi({
      VITE_API_BASE_URL: "http://localhost:8000",
      VITE_DATA_MODE: "mock",
    });

    expect(api).toBeInstanceOf(MockWorkbenchApi);
  });

  it("selects the HTTP implementation", () => {
    const api = createWorkbenchApi({
      VITE_API_BASE_URL: "http://localhost:8000",
      VITE_DATA_MODE: "api",
    });

    expect(api).toBeInstanceOf(HttpWorkbenchApi);
  });

  it("throws a typed configuration error for every unsupported mode", () => {
    expect(() =>
      createWorkbenchApi({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: "live",
      }),
    ).toThrowError(WorkbenchConfigurationError);

    try {
      createWorkbenchApi({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: undefined,
      });
    } catch (error: unknown) {
      expect(error).toBeInstanceOf(WorkbenchConfigurationError);
      if (error instanceof WorkbenchConfigurationError) {
        expect(error.code).toBe("INVALID_DATA_MODE");
      }
    }
  });
});

describe("HttpWorkbenchApi", () => {
  it("rejects malformed HTTP response data instead of coercing it", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          markets: [{ symbol: "BTCUSDT", price: 68_000 }],
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getDashboard()).rejects.toThrow(/response/i);
  });

  it("maps page_size only at the HTTP wire boundary", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          items: [],
          page: 2,
          page_size: 25,
          total: 0,
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.listReports({ page: 2, pageSize: 25 })).resolves.toEqual({
      items: [],
      page: 2,
      pageSize: 25,
      total: 0,
    });
  });

  it("forwards an AbortSignal to HTTP requests", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          items: [],
          page: 1,
          page_size: 20,
          total: 0,
        }),
      ),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });
    const controller = new AbortController();

    await api.listReports({ page: 1, pageSize: 20 }, controller.signal);

    expect(fetchImpl).toHaveBeenCalledWith(
      expect.any(URL),
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});
