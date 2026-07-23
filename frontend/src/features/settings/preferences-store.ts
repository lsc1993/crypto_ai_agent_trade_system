import { z } from "zod";

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
    theme: z.enum(["dark", "light", "system"]),
    displayTimezone: timeZoneSchema,
    refreshPreference: z.enum(["manual", "auto"]),
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

export function loadPreferences(): Preferences {
  if (typeof localStorage === "undefined") {
    return { ...DEFAULT_PREFERENCES };
  }

  const raw = localStorage.getItem(PREFERENCES_STORAGE_KEY);
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

  localStorage.removeItem(PREFERENCES_STORAGE_KEY);
  return { ...DEFAULT_PREFERENCES };
}

export function savePreferences(input: unknown): Preferences {
  const preferences = preferencesSchema.parse(input);
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(
      PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        theme: preferences.theme,
        displayTimezone: preferences.displayTimezone,
        refreshPreference: preferences.refreshPreference,
      }),
    );
  }
  return preferences;
}
