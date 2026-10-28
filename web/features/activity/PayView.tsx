"use client";

import { SummaryPanel } from "@/components/pnl/SummaryPanel";
import { Card } from "@/components/ui/Card";
import { todayInNewYork } from "@/features/trades/time";
import { Curve } from "./Curve";
import { LegsCard, LegsFilters } from "./Legs";
import { PayMonth } from "./PayMonth";
import { currentMonth, earliestMonth } from "./month";
import { useEquity } from "./useEquity";
import { useLegFilters } from "./useLegFilters";
import { useMonthParam } from "./useMonthParam";

/**
 * Pay: a month as a stub, one row of filters, then what they narrow: the totals since the system
 * began, the equity curve and the legs. The month is the page's (`?month=`); the filters are local
 * and shared by the three cards under them.
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
      <LegsFilters filters={legs.filters} formKey={legs.formKey} onFilters={legs.setFilters} />
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
      <Curve qsString={legs.qsString} />
      <LegsCard qsString={legs.qsString} />
    </div>
  );
}
