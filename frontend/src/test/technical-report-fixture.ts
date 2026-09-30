export const technicalReportWire = {
  version: "technical-v1",
  id: "00000000-0000-4000-8000-000000000101",
  analysisId: "00000000-0000-4000-8000-000000000102",
  symbol: "BTCUSDT",
  status: "completed",
  createdAt: "2026-09-29T12:00:00Z",
  dataCutoffAt: "2026-09-29T11:00:00Z",
  analysis: {
    quality: { status: "valid", reasons: [], candleCounts: { "1d": 60, "4h": 60, "1h": 60 }, latestClosedAt: { "1d": "2026-09-29T00:00:00Z", "4h": "2026-09-29T08:00:00Z", "1h": "2026-09-29T11:00:00Z" } },
    facts: { trendAlignment: { "1d": "bullish", "4h": "bullish", "1h": "bullish" }, sma20: { "1d": "69000" }, sma50: { "1d": "67000" }, atr14: "200", rangeHigh: "70000", rangeLow: "68000", volumeRatio: "1.6", volumeSignal: "high", smallBody: false, longUpperWick: false, longLowerWick: true, breakout: "none", supportLevels: ["69000"], resistanceLevels: ["72000"] },
    plans: [{ direction: "long", state: "awaiting_confirmation", triggerLevel: "70000", entryLower: "69900", entryUpper: "70100", stopLoss: "69500", target: "72000", rewardRisk: "2.1", feeRatePerSide: "0.0005", slippageRatePerSide: "0.0005", validUntil: "2026-09-29T15:00:00Z", rationale: "awaiting_closed_volume_breakout_with_structural_target" }],
    noPlanReasons: [],
    methods: [{ id: "volume_price", version: "v1", sourceSkillId: "original-skill", sourceSha256: "a".repeat(64), adaptedSha256: "b".repeat(64), adaptationNote: "量价方法经项目边界改编" }],
    evidenceId: "00000000-0000-4000-8000-000000000103",
  },
  narrative: { thesis: { text: "量价结构偏强。", evidenceIds: ["00000000-0000-4000-8000-000000000103"] }, alternative: { text: "若未确认，仍需等待。", evidenceIds: ["00000000-0000-4000-8000-000000000103"] }, risks: [{ text: "波动可能扩大。", evidenceIds: ["00000000-0000-4000-8000-000000000103"] }] },
  errorCode: null,
} as const;
