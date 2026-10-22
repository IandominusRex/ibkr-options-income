import clsx from "clsx";
import type { ReactNode } from "react";

export type FigureRow = {
  label: ReactNode;
  value: ReactNode;
  /** A value we do not have: hatched, never blank and never zero. */
  unknown?: boolean;
};

/**
 * Figure lines under a perforation, in the stub face: the payslip's voice for numbers Python
 * computed. The Stub component sums money; this one only lists, so it takes any text.
 */
export function FigureLines({ label, rows }: { label: string; rows: FigureRow[] }) {
  return (
    <div
      role="group"
      aria-label={label}
      className="tabular mt-3 border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium"
    >
      <dl>
        {rows.map((r, i) => (
          <div key={i} className="flex min-h-6 items-baseline justify-between gap-3">
            <dt className="min-w-0">{r.label}</dt>
            <dd className={clsx("text-right", r.unknown && "hatch text-unknown")}>{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
