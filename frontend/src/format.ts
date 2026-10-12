import Decimal from "decimal.js";
import type { Overview } from "./types";
export function numeric(value: unknown): Decimal | null {
  try {
    if (typeof value !== "string" && typeof value !== "number") return null;
    const n = new Decimal(value);
    return n.isFinite() ? n : null;
  } catch {
    return null;
  }
}
export function percent(value: unknown, fraction = false): string {
  const n = numeric(value);
  return n ? n.mul(fraction ? 100 : 1).toFixed(1) + "%" : "Not available";
}
export function money(value: unknown, currency: string): string {
  const n = numeric(value);
  return n
    ? currency + " " + n.toFixed(Math.max(4, Math.min(8, n.decimalPlaces())))
    : "Not available";
}
const cstTime = new Intl.DateTimeFormat("en-US", {
  timeZone: "Etc/GMT+6",
  month: "short", day: "2-digit", year: "numeric",
  hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true,
});

export function date(value: string | null | undefined): string {
  if (!value) return "Not available";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "Not available"
    : cstTime.format(parsed) + " CST";
}
export function telemetryState(data: Overview): string {
  if (
    !data.inventory_servers ||
    data.no_data_servers === data.inventory_servers
  )
    return "NO_DATA";
  if (
    data.stale_servers &&
    !data.healthy_servers &&
    !data.warning_servers &&
    !data.critical_servers
  )
    return "STALE";
  return data.stale_servers || data.no_data_servers ? "PARTIAL" : "FRESH";
}
