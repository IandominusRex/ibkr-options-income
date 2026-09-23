/**
 * A labelled range on a 0-100 scale, e.g. "CSP delta target: 0.15-0.30" drawn against
 * "0.0 (deep OTM) .. 1.0 (deep ITM)". Mirrors the artifact-report band bars this tab was
 * asked to match, rebuilt on this app's own tokens: the track is a raised surface
 * (elevation, not a colour choice), the filled range is bounded by the app's one accent
 * colour, and - since a bar's value is never allowed to animate in here - it renders at
 * its final width immediately. The bound labels sit above the track rather than inside
 * the fill, so a narrow band (a tight delta window) never has its own two numbers
 * colliding into each other.
 */
export function RangeBar({
  label,
  lowPct,
  highPct,
  lowText,
  highText,
  scaleLeft,
  scaleRight,
}: {
  label: string;
  lowPct: number;
  highPct: number;
  lowText: string;
  highText: string;
  scaleLeft: string;
  scaleRight: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-3">
        <div className="w-32 shrink-0 text-xs text-muted">{label}</div>
        <div className="relative flex-1">
          <div className="relative mb-4 h-4 font-mono text-[11px] text-focus">
            <span
              className="absolute -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${lowPct}%` }}
            >
              {lowText}
            </span>
            <span
              className="absolute -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${highPct}%` }}
            >
              {highText}
            </span>
          </div>
          <div className="relative h-2.5 rounded-full border border-border bg-elevated">
            <div
              className="absolute inset-y-0 rounded-full border-x-2 border-focus bg-focus/25"
              style={{ left: `${lowPct}%`, right: `${100 - highPct}%` }}
            />
          </div>
        </div>
      </div>
      <div className="ml-[8.75rem] mt-1 flex justify-between font-mono text-[10px] text-muted">
        <span>{scaleLeft}</span>
        <span>{scaleRight}</span>
      </div>
    </div>
  );
}
