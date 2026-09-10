import type { ReactNode } from "react";
import { UNKNOWN } from "@/lib/format";
import { Money } from "./Money";
import type { OptionLeg } from "./types";

function Field({
  label,
  children,
  testId,
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}

function Unknown() {
  return <span className="hatch text-unknown">{UNKNOWN}</span>;
}

/**
 * One option leg of a `PositionGroup`. Every "state" the brief calls out
 * renders as a word, not a colour or an implied default:
 * - direction (`short`) is spelled "Short"/"Long", never left to a negative
 *   contract count (`contracts` is always the absolute value per the API).
 * - `assignment_risk: true` renders the words "Assignment risk", no dot.
 * - `dte`/`moneyness` render `n/a` for `null` rather than `0`/`"otm"`.
 * - `delta` renders beside its `delta_source`, matching
 *   `components/options/ShortsRow.tsx`'s delta cell.
 */
export function OptionLegRow({ option }: { option: OptionLeg }) {
  const direction = option.short ? "Short" : "Long";

  return (
    <div
      className="grid grid-cols-2 gap-x-4 gap-y-2 py-2 sm:grid-cols-4"
      data-testid="option-leg"
    >
      <Field label="Contract">
        <span className="font-mono text-xs text-content">
          {option.right ?? UNKNOWN} {option.strike != null ? option.strike.toFixed(2) : UNKNOWN}
        </span>
        <span className="block text-xs text-muted">{option.expiry ?? UNKNOWN}</span>
      </Field>
      <Field label="Direction" testId="option-direction">
        <span className="text-content">{direction}</span>
      </Field>
      <Field label="Contracts">
        <span className="tabular text-content">{option.contracts}</span>
      </Field>
      <Field label="DTE" testId="option-dte">
        <span className="tabular text-content" data-testid="option-dte-value">
          {option.dte != null ? option.dte : <Unknown />}
        </span>
      </Field>
      <Field label="Moneyness" testId="option-moneyness">
        <span className="text-content">{option.moneyness ?? <Unknown />}</span>
      </Field>
      <Field label="Delta" testId="option-delta">
        {option.delta != null ? (
          <span className="tabular text-content">
            {option.delta.toFixed(2)}
            {option.delta_source && <span className="ml-1 text-muted">{option.delta_source}</span>}
          </span>
        ) : (
          <Unknown />
        )}
      </Field>
      <Field label="Market price">
        <Money value={option.market_price} kind="value" asOf={option.as_of} />
      </Field>
      <Field label="Market value">
        <Money value={option.market_value} kind="value" asOf={option.as_of} />
      </Field>
      <Field label="Unrealized P&L">
        <Money value={option.unrealized_pnl} kind="unrealized" signed asOf={option.as_of} />
      </Field>
      {option.assignment_risk && (
        <Field label="Status">
          <span className="text-unknown">Assignment risk</span>
        </Field>
      )}
    </div>
  );
}
