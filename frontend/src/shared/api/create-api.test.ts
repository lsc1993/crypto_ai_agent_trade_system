import { afterEach, describe, expect, it, vi } from "vitest";
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
import { mockTradeDraft } from "../mocks/fixtures";

describe("createWorkbenchApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

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

  it("forwards the persisted research source to the hybrid market client", async () => {
    const fetchImpl: typeof fetch = vi.fn((input: RequestInfo | URL) => {
      const requestUrl =
        input instanceof URL
          ? input
          : new URL(typeof input === "string" ? input : input.url);
      const { pathname } = requestUrl;
      if (pathname === "/api/v1/research/markets") {
        return Promise.resolve(Response.json({ items: [] }));
      }
      if (pathname === "/api/v1/analysis-runs") {
        return Promise.resolve(
          Response.json({ items: [], page: 1, page_size: 20, total: 0 }),
        );
      }
      return Promise.reject(new Error(`Unexpected local API path: ${pathname}`));
    });
    vi.stubGlobal("fetch", fetchImpl);
    const api = createWorkbenchApi({
      VITE_API_BASE_URL: "http://localhost:8000",
      VITE_DATA_MODE: "market-api",
      VITE_MARKET_DATA_SOURCE: "research",
    });

    await expect(api.getDashboard()).resolves.toMatchObject({ markets: [] });

    const requestUrls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls.map(
      ([input]) => new URL(input as URL),
    );
    expect(requestUrls.map((requestUrl) => requestUrl.pathname)).toEqual([
      "/api/v1/research/markets",
      "/api/v1/analysis-runs",
    ]);
    expect(requestUrls[1]?.searchParams.get("page")).toBe("1");
    expect(requestUrls[1]?.searchParams.get("page_size")).toBe("20");
  });

  it("routes journal and analytics requests through the configured local API", async () => {
    const journalTrade = {
      ...mockTradeDraft,
      id: "trade-001",
      cashflows: mockTradeDraft.fundingCashflows,
      status: "open",
      netPnl: "0.00",
      openedAt: "2026-07-31T00:00:00Z",
      closedAt: null,
      createdAt: "2026-07-31T00:00:00Z",
      updatedAt: "2026-07-31T00:00:00Z",
    };
    const fetchImpl: typeof fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl =
        input instanceof URL
          ? input
          : new URL(typeof input === "string" ? input : input.url);
      if (requestUrl.pathname === "/api/v1/trades" && init?.method === undefined) {
        return Promise.resolve(
          Response.json({
            items: [journalTrade],
            page: 1,
            page_size: 20,
            total: 1,
          }),
        );
      }
      if (requestUrl.pathname === "/api/v1/trades" && init?.method === "POST") {
        return Promise.resolve(Response.json(journalTrade));
      }
      if (
        requestUrl.pathname === "/api/v1/trades/trade-001" &&
        init?.method === "PUT"
      ) {
        return Promise.resolve(Response.json(journalTrade));
      }
      if (requestUrl.pathname === "/api/v1/analytics") {
        return Promise.resolve(
          Response.json({
            netPnl: "0.00",
            winRate: "0",
            profitFactor: null,
            expectancy: "0.00",
            maxDrawdown: "0.00",
            equityCurve: [],
            tradeCalendar: [],
            generatedAt: "2026-07-31T00:00:00Z",
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected local API path: ${requestUrl.pathname}`));
    });
    vi.stubGlobal("fetch", fetchImpl);
    const api = createWorkbenchApi({
      VITE_API_BASE_URL: "http://localhost:8000",
      VITE_DATA_MODE: "market-api",
    });

    await expect(api.listTrades({ page: 1, pageSize: 20 })).resolves.toMatchObject({
      items: [{ id: "trade-001" }],
    });
    await expect(api.createTrade(mockTradeDraft)).resolves.toMatchObject({
      fundingCashflows: [],
    });
    await expect(api.updateTrade("trade-001", mockTradeDraft)).resolves.toMatchObject({
      id: "trade-001",
    });
    await expect(api.getAnalytics({})).resolves.toMatchObject({
      profitFactor: null,
    });

    const requestUrls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls.map(
      ([input]) => new URL(input as URL),
    );
    expect(requestUrls.map((requestUrl) => requestUrl.pathname)).toEqual([
      "/api/v1/trades",
      "/api/v1/trades",
      "/api/v1/trades/trade-001",
      "/api/v1/analytics",
    ]);
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
