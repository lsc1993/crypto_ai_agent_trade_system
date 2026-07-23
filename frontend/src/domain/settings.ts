import { z } from "zod";

export const userPreferencesSchema = z.object({
  theme: z.enum(["dark", "light", "system"]),
  displayTimezone: z.string().trim().min(1),
  refreshIntervalSeconds: z.number().int().min(15).max(3600),
});

export type UserPreferences = z.infer<typeof userPreferencesSchema>;
