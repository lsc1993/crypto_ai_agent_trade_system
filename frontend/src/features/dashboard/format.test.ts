import { describe, expect, it } from "vitest";

import {
  formatDailyChange,
  formatFundingRate,
} from "../../shared/format";

describe("market percentage formatting", () => {
  it("does not label a zero value as a positive change", () => {
    expect(formatDailyChange("0")).toBe("0.00%");
    expect(formatFundingRate("0")).toBe("0.0000%");
  });

  it("normalizes a tiny negative funding rate that rounds to zero", () => {
    expect(formatFundingRate("-0.0000001")).toBe("0.0000%");
  });
});
