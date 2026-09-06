import { UNKNOWN } from "@/lib/format";
import type { IdealZonePayload } from "./types";

// The ideal zone renders as a bar with the actual premium marked against lo, hi
// and min_credit, with numbers visible. No fabricated precision: render at the
// precision the source provides.
export function IdealZoneBar({
  ideal,
  premium,
}: {
  ideal: IdealZonePayload;
  premium: number | null;
}) {
  const lo = ideal.lo;
  const hi = ideal.hi;
  const minCredit = ideal.min_credit;

  if (lo == null && hi == null && minCredit == null) {
    return <p className="text-xs text-muted">No ideal zone derived.</p>;
  }

  // Build a scale from the available numbers so the bar is proportional.
  const vals = [lo, hi, minCredit, premium].filter(
    (v): v is number => v != null && !Number.isNaN(v),
  );
  if (vals.length === 0) {
    return (
      <div className="text-xs text-muted">
        lo {fmt(lo)} - hi {fmt(hi)} - min credit {fmt(minCredit)}
      </div>
    );
  }
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const pct = (v: number) => ((v - min) / range) * 100;

  return (
    <div className="space-y-1">
      <div className="relative h-6 rounded-sm bg-surface">
        {/* lo to hi band */}
        {lo != null && hi != null && (
          <div
            className="absolute top-0 h-full rounded-sm bg-elevated"
            style={{
              left: `${Math.min(pct(lo), pct(hi))}%`,
              width: `${Math.abs(pct(hi) - pct(lo))}%`,
            }}
          />
        )}
        {/* min_credit marker */}
        {minCredit != null && (
          <Marker pct={pct(minCredit)} label="min" />
        )}
        {/* premium marker */}
        {premium != null && (
          <Marker pct={pct(premium)} label="premium" highlight />
        )}
      </div>
      <div className="flex gap-4 text-xs text-muted tabular">
        <span>lo {fmt(lo)}</span>
        <span>hi {fmt(hi)}</span>
        <span>min credit {fmt(minCredit)}</span>
        <span>premium {fmt(premium)}</span>
      </div>
    </div>
  );
}

function Marker({
  pct,
  label,
  highlight,
}: {
  pct: number;
  label: string;
  highlight?: boolean;
}) {
  return (
    <div
      className="absolute top-0 h-full w-px"
      style={{ left: `${pct}%` }}
      aria-label={label}
    >
      <div
        className={
          "absolute -top-3 -translate-x-1/2 text-[10px] " +
          (highlight ? "text-content" : "text-muted")
        }
      >
        {label}
      </div>
    </div>
  );
}

function fmt(v: number | null): string {
  if (v == null) return UNKNOWN;
  return `$${v.toFixed(2)}`;
}