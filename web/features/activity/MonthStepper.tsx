import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { monthLabel, shiftMonth } from "./month";

/**
 * Previous, the month, This month (away from it) and next. Next stops at the current month, and
 * previous at `floor`, the month the system began, when that is known. A disabled quiet button
 * shows as a filled circle (the Open Decision in web/DESIGN.md), as History's day arrows do.
 */
export function MonthStepper({
  month,
  current,
  floor,
  onChange,
}: {
  month: string;
  current: string;
  floor: string | null;
  onChange: (month: string) => void;
}) {
  return (
    <nav aria-label="Month" className="flex items-center justify-between gap-2">
      <Button
        variant="quiet"
        aria-label="Previous month"
        disabled={floor !== null && month <= floor}
        onClick={() => onChange(shiftMonth(month, -1))}
        className="w-11 !px-0"
      >
        <ChevronLeft size={18} strokeWidth={2.25} aria-hidden="true" />
      </Button>
      <p aria-live="polite" className="text-[1.0625rem] font-bold">
        {monthLabel(month)}
      </p>
      <div className="flex items-center gap-1">
        {month !== current && (
          <Button variant="secondary" onClick={() => onChange(current)}>
            This month
          </Button>
        )}
        <Button
          variant="quiet"
          aria-label="Next month"
          disabled={month >= current}
          onClick={() => onChange(shiftMonth(month, 1))}
          className="w-11 !px-0"
        >
          <ChevronRight size={18} strokeWidth={2.25} aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}
