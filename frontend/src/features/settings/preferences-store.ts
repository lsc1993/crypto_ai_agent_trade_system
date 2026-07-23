import { z } from "zod";

const themeSchema = z.enum(["dark", "light", "system"]);
const refreshPreferenceSchema = z.enum(["manual", "auto"]);
const timeZoneSchema = z
  .string()
  .trim()
  .min(1)
  .refine(
    (value) => {
      try {
        new Intl.DateTimeFormat("zh-CN", { timeZone: value });
        return true;
      } catch {
        return false;
      }
    },
    { message: "显示时区无效" },
  );

const preferencesSchema = z
  .object({
    theme: themeSchema,
    displayTimezone: timeZoneSchema,
    refreshPreference: refreshPreferenceSchema,
  })
  .strict();

export type Preferences = z.infer<typeof preferencesSchema>;

export const PREFERENCES_STORAGE_KEY =
  "crypto-workbench:display-preferences:v1";

export const DEFAULT_PREFERENCES: Preferences = {
  theme: "system",
  displayTimezone: "UTC",
  refreshPreference: "manual",
};

export class PreferencesStorageError extends Error {
  constructor(
    readonly operation: "read" | "purge" | "write",
  ) {
    super("Browser preference storage is unavailable");
    this.name = "PreferencesStorageError";
  }
}

export function parseThemePreference(
  value: unknown,
): Preferences["theme"] | undefined {
  const result = themeSchema.safeParse(value);
  return result.success ? result.data : undefined;
}

export function parseDisplayTimezone(
  value: unknown,
): Preferences["displayTimezone"] | undefined {
  const result = timeZoneSchema.safeParse(value);
  return result.success ? result.data : undefined;
}

export function parseRefreshPreference(
  value: unknown,
): Preferences["refreshPreference"] | undefined {
  const result = refreshPreferenceSchema.safeParse(value);
  return result.success ? result.data : undefined;
}

export function loadPreferences(): Preferences {
  if (typeof localStorage === "undefined") {
    return { ...DEFAULT_PREFERENCES };
  }

  let raw: string | null;
  try {
    raw = localStorage.getItem(PREFERENCES_STORAGE_KEY);
  } catch {
    throw new PreferencesStorageError("read");
  }
  if (raw === null) {
    return { ...DEFAULT_PREFERENCES };
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    const result = preferencesSchema.safeParse(parsed);
    if (result.success) {
      return result.data;
    }
  } catch {
    // 无效的浏览器本地数据会在下方被清理。
  }

  try {
    localStorage.removeItem(PREFERENCES_STORAGE_KEY);
  } catch {
    throw new PreferencesStorageError("purge");
  }
  return { ...DEFAULT_PREFERENCES };
}

export function savePreferences(input: unknown): Preferences {
  const preferences = preferencesSchema.parse(input);
  if (typeof localStorage !== "undefined") {
    try {
      localStorage.setItem(
        PREFERENCES_STORAGE_KEY,
        JSON.stringify({
          theme: preferences.theme,
          displayTimezone: preferences.displayTimezone,
          refreshPreference: preferences.refreshPreference,
        }),
      );
    } catch {
      throw new PreferencesStorageError("write");
    }
  }
  return preferences;
}
