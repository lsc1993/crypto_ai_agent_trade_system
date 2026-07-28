import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { HttpTransport } from "./http-transport";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HttpTransport", () => {
  it("calls the browser global fetch with its required receiver", async () => {
    const runtimeFetch = vi.fn(function (this: typeof globalThis) {
      if (this !== globalThis) {
        throw new TypeError("global fetch must use the global receiver");
      }
      return Promise.resolve(Response.json({ status: "ok" }));
    });
    vi.stubGlobal("fetch", runtimeFetch);
    const transport = new HttpTransport({
      baseUrl: "http://127.0.0.1:8000",
    });

    await expect(
      transport.request("/healthz", z.object({ status: z.literal("ok") })),
    ).resolves.toEqual({ status: "ok" });
  });
});
