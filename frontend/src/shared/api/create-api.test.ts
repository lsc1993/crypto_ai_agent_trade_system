import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { createWorkbenchApi } from "./create-api";
import {
  HttpWorkbenchApi,
  WorkbenchEndpointUnavailableError,
} from "./http-workbench-api";
import { HybridWorkbenchApi } from "./hybrid-workbench-api";
import {
  createWirePageSchema,
  HttpTransport,
} from "./http-transport";
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

  it("selects the hybrid implementation for public market data", () => {
    const api = createWorkbenchApi({
      VITE_API_BASE_URL: "http://localhost:8000",
      VITE_DATA_MODE: "market-api",
    });

    expect(api).toBeInstanceOf(HybridWorkbenchApi);
  });

  it("throws a typed configuration error for every unsupported mode", () => {
    expect(() =>
      createWorkbenchApi({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: "live",
      }),
    ).toThrowError(WorkbenchConfigurationError);

    expect(() =>
      createWorkbenchApi({
        VITE_API_BASE_URL: "http://localhost:8000",
        VITE_DATA_MODE: undefined,
      }),
    ).toThrowError(
      expect.objectContaining({
        code: "INVALID_DATA_MODE",
      }),
    );
  });
});

describe("HttpTransport", () => {
  it("rejects malformed HTTP response data instead of coercing it", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.resolve(
        Response.json({
          markets: [{ symbol: "BTCUSDT", price: 68_000 }],
        }),
      ),
    );
    const transport = new HttpTransport({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(
      transport.request("/contract-test", z.object({ status: z.literal("ok") })),
    ).rejects.toThrow(/response/i);
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
    const transport = new HttpTransport({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(
      transport.request(
        "/contract-test",
        createWirePageSchema(z.object({ id: z.string() })),
      ),
    ).resolves.toEqual({
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
    const transport = new HttpTransport({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });
    const controller = new AbortController();

    await transport.request(
      "/contract-test",
      createWirePageSchema(z.object({ id: z.string() })),
      { signal: controller.signal },
    );

    expect(fetchImpl).toHaveBeenCalledWith(
      expect.any(URL),
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});

describe("HttpWorkbenchApi", () => {
  it("signals that business endpoints are unavailable until routes exist", async () => {
    const fetchImpl: typeof fetch = vi.fn(() =>
      Promise.reject(new Error("fetch must not be called")),
    );
    const api = new HttpWorkbenchApi({
      baseUrl: "http://localhost:8000",
      fetchImpl,
    });

    await expect(api.getDashboard()).rejects.toBeInstanceOf(
      WorkbenchEndpointUnavailableError,
    );
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
