import { OptionLegRow } from "./OptionLegRow";
import { StockLegRow } from "./StockLegRow";
import type { PositionGroupData } from "./types";

/**
 * One underlying's position group: the ticker once, the stock leg (if any)
 * above its option legs (if any). Pure and prop-driven - `PositionsPanel`
 * fetches the list and renders one of these per group, this component does
 * no fetching of its own.
 */
export function PositionGroup({ group }: { group: PositionGroupData }) {
  return (
    <section
      className="rounded-md border border-border bg-surface p-4"
      data-testid="position-group"
    >
      <h3 className="font-mono text-sm text-content">{group.underlying}</h3>

      {group.stock && (
        <div className="mt-3">
          <StockLegRow stock={group.stock} />
        </div>
      )}

      {group.options.length > 0 && (
        <div className="mt-3 divide-y divide-border">
          {group.options.map((option) => (
            <OptionLegRow option={option} key={option.symbol} />
          ))}
        </div>
      )}
    </section>
  );
}
