import Decimal from "decimal.js";

import type { DecimalString } from "../domain/primitives";

interface DecimalDisplayOptions {
  minimumFractionDigits?: number;
  showPositiveSign?: boolean;
}

function groupInteger(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function isZeroDecimal(value: string): boolean {
  return /^0(?:\.0+)?$/.test(value);
}

export function formatDecimal(
  value: DecimalString,
  options: DecimalDisplayOptions = {},
): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [integer = "0", currentFraction = ""] = unsigned.split(".");
  const minimumFractionDigits = options.minimumFractionDigits ?? 0;
  const fraction = currentFraction.padEnd(minimumFractionDigits, "0");
  const sign = negative
    ? "-"
    : options.showPositiveSign && !isZeroDecimal(unsigned)
      ? "+"
      : "";

  return `${sign}${groupInteger(integer)}${
    fraction.length > 0 ? `.${fraction}` : ""
  }`;
}

export function formatMarketPrice(value: DecimalString): string {
  return formatDecimal(value, { minimumFractionDigits: 2 });
}

export function formatMarketVolume(value: DecimalString): string {
  return formatDecimal(value);
}

export function formatOpenInterest(value: DecimalString): string {
  return formatDecimal(value);
}

export function formatDailyChange(value: DecimalString): string {
  return `${formatDecimal(value, {
    minimumFractionDigits: 2,
    showPositiveSign: true,
  })}%`;
}

export function formatFundingRate(value: DecimalString): string {
  const percent = new Decimal(value).mul(100).toFixed(4);
  return `${formatDecimal(percent, { showPositiveSign: true })}%`;
}
