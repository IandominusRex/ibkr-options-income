"use client";

import { SummaryPanel } from "@/components/pnl/SummaryPanel";
import { Card } from "@/components/ui/Card";
import { todayInNewYork } from "@/features/trades/time";
import { PayMonth } from "./PayMonth";
import { currentMonth, earliestMonth } from "./month";
import { useEquity } from "./useEquity";
import { useLegFilters } from "./useLegFilters";
import { useMonthParam } from "./useMonthParam";

/**
 * Pay: a month as a stub, then the totals since the system began. (The equity curve and the legs
 * join it in the next task, under the same filters.)
 */
export function PayView() {
  const current = currentMonth(todayInNewYork());
  const [month, setMonth] = useMonthParam(current);
  const legs = useLegFilters();
  const equity = useEquity(legs.qsString);
  const floor = earliestMonth(equity.data?.curve.starts_at);

  return (
    <div className="grid gap-4">
      <PayMonth month={month} current={current} floor={floor} onMonth={setMonth} />
      <Card aria-labelledby="totals-title">
        <h2 id="totals-title" className="text-[1.0625rem] font-bold">
          Since the system began
        </h2>
        <div className="mt-3">
          <SummaryPanel
            book={legs.book}
            qsString={legs.qsString}
            onBookChange={legs.setBook}
            onSelectLeg={legs.viewLeg}
          />
        </div>
      </Card>
    </div>
  );
}
