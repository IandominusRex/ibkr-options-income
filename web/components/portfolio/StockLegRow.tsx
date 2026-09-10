import type { ReactNode } from "react";
import { Money } from "./Money";
import type { StockLeg } from "./types";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}

/**
 * One stock leg of a `PositionGroup` - shares, cost basis, market value, and
 * unrealized P&L. `avg_cost` (what IBKR reports) always renders; the
 * premium-adjusted pair (`adjusted_cost_basis` / `unrealized_pnl_adjusted`)
 * renders only when the campaign lookup found one, and its label names it
 * "premium-adjusted" in words - a null `adjusted_cost_basis` renders no
 * adjusted row at all, never an n/a row implying the concept applies here.
 */
export function StockLegRow({ stock }: { stock: StockLeg }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4" data-testid="stock-leg">
      <Field label="Shares">
        <span className="tabular text-content">{stock.shares}</span>
      </Field>
      <Field label="Cost basis">
        <Money value={stock.avg_cost} kind="basis" asOf={stock.as_of} />
      </Field>
      <Field label="Market value">
        <Money value={stock.market_value} kind="value" asOf={stock.as_of} />
      </Field>
      <Field label="Unrealized P&L">
        <Money value={stock.unrealized_pnl} kind="unrealized" signed asOf={stock.as_of} />
      </Field>
      {stock.adjusted_cost_basis != null && (
        <>
          <Field label="Adjusted cost basis (premium-adjusted)">
            <Money value={stock.adjusted_cost_basis} kind="basis" asOf={stock.as_of} />
          </Field>
          <Field label="Unrealized P&L (premium-adjusted)">
            <Money
              value={stock.unrealized_pnl_adjusted}
              kind="unrealized"
              signed
              asOf={stock.as_of}
            />
          </Field>
        </>
      )}
    </div>
  );
}
