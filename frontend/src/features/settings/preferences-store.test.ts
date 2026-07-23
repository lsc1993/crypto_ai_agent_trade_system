import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PREFERENCES,
  PREFERENCES_STORAGE_KEY,
  loadPreferences,
  savePreferences,
} from "./preferences-store";

describe("preferences-store", () => {
  it("returns safe validated defaults when storage is empty", () => {
    expect(loadPreferences()).toEqual({
      theme: "system",
      displayTimezone: "UTC",
      refreshPreference: "manual",
    });
  });

  it("persists exactly the three allowed display preference keys", () => {
    savePreferences({
      theme: "dark",
      displayTimezone: "Asia/Shanghai",
      refreshPreference: "auto",
    });

    const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY);
    const stored = JSON.parse(raw ?? "{}") as Record<string, unknown>;
    expect(Object.keys(stored).sort()).toEqual([
      "displayTimezone",
      "refreshPreference",
      "theme",
    ]);
    expect(stored).not.toHaveProperty("refreshIntervalSeconds");
    expect(stored).not.toHaveProperty("drafts");
    expect(stored).not.toHaveProperty("reports");
    expect(stored).not.toHaveProperty("accounts");
    expect(stored).not.toHaveProperty("apiKey");
  });

  it.each([
    [
      "legacy refresh interval",
      {
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        refreshIntervalSeconds: 30,
      },
    ],
    [
      "trade drafts",
      {
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        drafts: [{ symbol: "BTCUSDT" }],
      },
    ],
    [
      "raw reports",
      {
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        reports: [{ id: "report-copy" }],
      },
    ],
    [
      "account data",
      {
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        accounts: [{ exchange: "example" }],
      },
    ],
    [
      "credential-like data",
      {
        theme: "system",
        displayTimezone: "UTC",
        refreshPreference: "manual",
        apiKey: "must-never-persist",
      },
    ],
  ])("rejects %s without persisting it", (_, preferences) => {
    expect(() => savePreferences(preferences)).toThrow();
    expect(localStorage.getItem(PREFERENCES_STORAGE_KEY)).toBeNull();
  });

  it.each([
    { theme: "neon" },
    { displayTimezone: "" },
    { displayTimezone: "Not/A-Timezone" },
    { refreshPreference: "15-seconds" },
  ])("rejects invalid allowlisted values: %o", (invalidField) => {
    expect(() =>
      savePreferences({
        ...DEFAULT_PREFERENCES,
        ...invalidField,
      }),
    ).toThrow();
    expect(localStorage.getItem(PREFERENCES_STORAGE_KEY)).toBeNull();
  });

  it("falls back safely for corrupted or non-allowlisted localStorage", () => {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, "{not-json");
    expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);

    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_PREFERENCES,
        reports: [{ id: "report-copy" }],
      }),
    );
    expect(loadPreferences()).toEqual(DEFAULT_PREFERENCES);
  });

  it("surfaces localStorage read, purge, and write failures for the UI boundary", () => {
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("storage read failed", "SecurityError");
      });
    expect(() => loadPreferences()).toThrow();
    getItem.mockRestore();

    vi.spyOn(Storage.prototype, "getItem").mockReturnValue("{not-json");
    const removeItem = vi
      .spyOn(Storage.prototype, "removeItem")
      .mockImplementation(() => {
        throw new DOMException("storage purge failed", "SecurityError");
      });
    expect(() => loadPreferences()).toThrow();
    removeItem.mockRestore();
    vi.restoreAllMocks();

    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("storage write failed", "QuotaExceededError");
    });
    expect(() => savePreferences(DEFAULT_PREFERENCES)).toThrow();
  });
});
