// Ledger number formatting. Unknown renders "n/a" - an unknown is never shown as zero.

export function money(v: number | null | undefined, currency = "USD"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  const abs = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const prefix = currency === "USD" ? "$" : `${currency} `;
  return `${v < 0 ? "-" : ""}${prefix}${abs}`;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "n/a" : `${v.toFixed(2)}%`;
}

export function rate(v: number | null | undefined): string {
  return v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-unknown";
  if (v > 0) return "text-gain";
  if (v < 0) return "text-loss";
  return "text-content";
}
