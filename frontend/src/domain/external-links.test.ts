import { describe, expect, it } from "vitest";

import { newsItemSchema } from "./news";
import { analysisEvidenceSchema } from "./report";

const news = {
  id: "news-link-test",
  title: "External link boundary",
  summary: "Only HTTP(S) source links are accepted.",
  source: "Test source",
  sourceUrl: "https://example.com/news",
  publishedAt: "2024-02-29T00:00:00Z",
  fetchedAt: "2024-02-29T00:01:00Z",
  symbols: ["BTCUSDT"],
};

const evidence = {
  id: "evidence-link-test",
  symbol: "BTCUSDT",
  source: "Test source",
  sourceUrl: "https://example.com/evidence",
  observedAt: "2024-02-29T00:00:00Z",
  summary: "External evidence summary.",
};

describe("external source URL boundaries", () => {
  it.each(["javascript:alert(1)", "data:text/html,unsafe"])(
    "rejects unsafe news URL %s",
    (sourceUrl) => {
      expect(() => newsItemSchema.parse({ ...news, sourceUrl })).toThrow();
    },
  );

  it.each(["javascript:alert(1)", "data:text/html,unsafe"])(
    "rejects unsafe evidence URL %s",
    (sourceUrl) => {
      expect(() =>
        analysisEvidenceSchema.parse({ ...evidence, sourceUrl }),
      ).toThrow();
    },
  );

  it.each(["http://example.com/source", "https://example.com/source"])(
    "accepts HTTP(S) source URL %s",
    (sourceUrl) => {
      expect(newsItemSchema.parse({ ...news, sourceUrl }).sourceUrl).toBe(
        sourceUrl,
      );
      expect(
        analysisEvidenceSchema.parse({ ...evidence, sourceUrl }).sourceUrl,
      ).toBe(sourceUrl);
    },
  );
});
