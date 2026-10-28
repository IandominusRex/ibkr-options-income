import type { ReactNode } from "react";

/**
 * The ledger's headline figures as lines under a perforation, in the stub face: the payslip's
 * voice for numbers Python computed, and not a grid of KPI tiles.
 */
export function TileList({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <dl
      data-testid={testId}
      className="tabular mt-3 border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium"
    >
      {children}
    </dl>
  );
}

/** One figure line. A value we do not have ("n/a") is hatched; `tone` carries a sign class. */
export function Tile({ id, label, value, tone }: { id: string; label: string; value: string; tone?: string }) {
  const unknown = value === "n/a";
  return (
    <div data-testid={`tile-${id}`} className="flex min-h-6 items-baseline justify-between gap-3">
      <dt className="min-w-0">{label}</dt>
      <dd className={`text-right ${unknown ? "hatch text-unknown" : (tone ?? "")}`}>{value}</dd>
    </div>
  );
}
