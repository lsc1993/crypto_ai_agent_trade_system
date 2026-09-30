import { describe, expect, it } from "vitest";

import { technicalReportSchema } from "./technical-report";

import { technicalReportWire } from "../test/technical-report-fixture";

describe("technical report contract", () => {
  it("accepts the complete camelCase report with decimal strings", () => {
    expect(technicalReportSchema.parse(technicalReportWire)).toEqual(technicalReportWire);
  });

  it("rejects numeric prices and hidden raw evidence", () => {
    expect(technicalReportSchema.safeParse({ ...technicalReportWire, analysis: { ...technicalReportWire.analysis, facts: { ...technicalReportWire.analysis.facts, rangeHigh: 70000 } } }).success).toBe(false);
    expect(technicalReportSchema.safeParse({ ...technicalReportWire, rawCandles: [] }).success).toBe(false);
  });
});
