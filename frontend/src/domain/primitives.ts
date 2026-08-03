import { z } from "zod";

export type DecimalString = string;
export type UtcIsoString = string;
export type Symbol = "BTCUSDT" | "ETHUSDT";
export type Timeframe = "15m" | "1h" | "4h" | "1d";

const canonicalDecimalPattern = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const unsignedDecimalPattern = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
const utcZuluPattern =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/;

function hasSupportedPrecision(value: string): boolean {
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  const parts = unsigned.split(".");
  const integer = parts[0];
  const fraction = parts[1] ?? "";
  if (integer === undefined) {
    return false;
  }
  return integer.length + fraction.length <= 38 && fraction.length <= 18;
}

function isNonZero(value: string): boolean {
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  return unsigned.replace(".", "").split("").some((digit) => digit !== "0");
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function isRealUtcCalendarTimestamp(value: string): boolean {
  const match = utcZuluPattern.exec(value);
  if (match === null) {
    return false;
  }
  const yearText = match[1];
  const monthText = match[2];
  const dayText = match[3];
  const hourText = match[4];
  const minuteText = match[5];
  const secondText = match[6];
  if (
    yearText === undefined ||
    monthText === undefined ||
    dayText === undefined ||
    hourText === undefined ||
    minuteText === undefined ||
    secondText === undefined
  ) {
    return false;
  }

  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (
    month < 1 ||
    month > 12 ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return false;
  }
  const daysInMonth = [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  const maximumDay = daysInMonth[month - 1];
  return maximumDay !== undefined && day >= 1 && day <= maximumDay;
}

export const decimalStringSchema = z
  .string()
  .regex(canonicalDecimalPattern, "Expected a canonical decimal string")
  .refine(hasSupportedPrecision, "Decimal exceeds 38 digits or 18 decimal places")
  .refine((value) => value !== "-0" && !/^-0\.0+$/.test(value), {
    message: "Negative zero is not canonical",
  });

export const positiveDecimalStringSchema = z
  .string()
  .regex(unsignedDecimalPattern, "Expected a canonical positive decimal string")
  .refine(hasSupportedPrecision, "Decimal exceeds 38 digits or 18 decimal places")
  .refine(isNonZero, "Expected a value greater than zero");

export const nonNegativeDecimalStringSchema = z
  .string()
  .regex(
    unsignedDecimalPattern,
    "Expected a canonical non-negative decimal string",
  )
  .refine(hasSupportedPrecision, "Decimal exceeds 38 digits or 18 decimal places");

export const utcIsoStringSchema = z
  .string()
  .regex(utcZuluPattern, "Expected an RFC3339 UTC timestamp ending in Z")
  .refine(isRealUtcCalendarTimestamp, {
    message: "Expected a valid UTC timestamp",
  });

export const httpUrlSchema = z.url().refine(
  (value) => {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  },
  { message: "Expected an HTTP(S) URL" },
);

export const symbolSchema = z.enum(["BTCUSDT", "ETHUSDT"]);
export const timeframeSchema = z.enum(["15m", "1h", "4h", "1d"]);
export const identifierSchema = z.string().trim().min(1).max(128);
export const uuidSchema = z.uuid();

export const dataFreshnessStatusSchema = z.enum([
  "fresh",
  "stale",
  "missing",
  "failed",
]);

export const dataFreshnessSchema = z.object({
  status: dataFreshnessStatusSchema,
  source: z.string().trim().min(1),
  observedAt: utcIsoStringSchema,
  fetchedAt: utcIsoStringSchema,
});

export type DataFreshness = z.infer<typeof dataFreshnessSchema>;

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export const paginationSchema = z.object({
  page: z.number().int().positive().default(1),
  pageSize: z.number().int().min(1).max(100).default(20),
});

export function pageSchema<T extends z.ZodType>(
  itemSchema: T,
): z.ZodObject<{
  items: z.ZodArray<T>;
  page: z.ZodNumber;
  pageSize: z.ZodNumber;
  total: z.ZodNumber;
}> {
  return z.object({
    items: z.array(itemSchema),
    page: z.number().int().positive(),
    pageSize: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  });
}
