import type { DecimalValue } from "@/lib/api/contracts";

function finiteNumber(value: DecimalValue | number | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function decimalSign(value: DecimalValue | null): "positive" | "negative" | "flat" {
  const parsed = finiteNumber(value);
  if (parsed === null || parsed === 0) {
    return "flat";
  }
  return parsed > 0 ? "positive" : "negative";
}

export function formatMoney(
  value: DecimalValue | null | undefined,
  currency = "USD",
): string {
  const parsed = finiteNumber(value);
  if (parsed === null) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed);
}

export function formatSignedMoney(
  value: DecimalValue | null | undefined,
  currency = "USD",
): string {
  const parsed = finiteNumber(value);
  if (parsed === null) {
    return "Unavailable";
  }
  const absolute = formatMoney(String(Math.abs(parsed)), currency);
  return parsed > 0 ? `+${absolute}` : parsed < 0 ? `−${absolute}` : absolute;
}

export function formatProbability(value: DecimalValue | null | undefined): string {
  const parsed = finiteNumber(value);
  return parsed === null ? "Unavailable" : `${(parsed * 100).toFixed(1)}%`;
}

export function formatSignedPercent(value: DecimalValue | null | undefined): string {
  const parsed = finiteNumber(value);
  if (parsed === null) {
    return "Unavailable";
  }
  const formatted = `${Math.abs(parsed * 100).toFixed(1)}%`;
  return parsed > 0 ? `+${formatted}` : parsed < 0 ? `−${formatted}` : formatted;
}

export function formatPrice(value: DecimalValue | null | undefined): string {
  const parsed = finiteNumber(value);
  return parsed === null ? "—" : `${Math.round(parsed * 100)}¢`;
}

export function formatCompactNumber(value: DecimalValue | null | undefined): string {
  const parsed = finiteNumber(value);
  if (parsed === null) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    parsed,
  );
}

export function formatTimestamp(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return "Unavailable";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Unavailable";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(parsed);
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
