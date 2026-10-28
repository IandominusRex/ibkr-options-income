"use client";

import { EquityChart } from "@/components/pnl/EquityChart";
import { Card } from "@/components/ui/Card";
import { useEquity } from "./useEquity";

/** The equity curve under the shared filters. A gap in the journal is a gap in the line. */
export function Curve({ qsString }: { qsString: string }) {
  const { data, isError } = useEquity(qsString);
  return (
    <Card aria-labelledby="curve-title">
      <h2 id="curve-title" className="text-[1.0625rem] font-bold">
        Equity curve
      </h2>
      <div className="mt-3">
        {isError && !data ? (
          <div className="text-sm text-muted">
            <p>Could not load the equity curve.</p>
            <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
          </div>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the equity curve" className="h-40 rounded-xl bg-sunk" />
        ) : (
          <EquityChart curve={data.curve} />
        )}
      </div>
    </Card>
  );
}
