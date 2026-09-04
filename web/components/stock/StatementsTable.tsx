import { UNKNOWN, formatMoney, formatPeriod } from "@/lib/format";

type Item = {
  line_item: string;
  value: number | null;
  concept: string | null;
  accn: string | null;
  filed: string | null;
  form: string | null;
};

type Period = { period_end: string; period_type: string; items: Record<string, Item> };
type Financials = { annual: Period[]; quarterly: Period[] };

// Fixed row order so the table reads like a statement, not a hash dump.
const ROWS: [string, string][] = [
  ["revenue", "Revenue"],
  ["cost_of_revenue", "Cost of revenue"],
  ["gross_profit", "Gross profit"],
  ["operating_income", "Operating income"],
  ["net_income", "Net income"],
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["stockholders_equity", "Shareholders equity"],
  ["operating_cash_flow", "Operating cash flow"],
  ["capital_expenditure", "Capital expenditure"],
];

function StatementBody({ periods }: { periods: Period[] }) {
  if (periods.length === 0) {
    return (
      <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
        No periods filed.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md bg-surface">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-4 py-3 text-left font-medium text-muted">Line item</th>
            {periods.map((p) => (
              <th
                key={p.period_end}
                className="tabular px-4 py-3 text-right font-mono font-medium text-muted"
              >
                {formatPeriod(p.period_end)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label]) => (
            <tr key={key} className="border-b border-border last:border-0">
              <td className="px-4 py-2 text-content">{label}</td>
              {periods.map((p) => {
                const item = p.items[key];
                // Hyphen, not an em dash, per web/CLAUDE.md "Zero em dashes in UI copy".
                const title = item
                  ? `${item.concept ?? ""} - ${item.form ?? ""} ${item.accn ?? ""} filed ${item.filed ?? ""}`
                  : "Not reported";
                const isUnknown = item?.value == null;
                return (
                  <td
                    key={p.period_end}
                    title={title}
                    className={`tabular px-4 py-2 text-right font-mono ${
                      isUnknown ? "hatch text-unknown" : "text-content"
                    }`}
                  >
                    {item ? formatMoney(item.value) : UNKNOWN}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatementsTable({ financials }: { financials: Financials }) {
  return (
    <div className="space-y-8">
      {financials.annual.length > 0 && (
        <section>
          <h3 className="mb-3 text-xs font-medium tracking-wide text-muted">
            Annual
          </h3>
          <StatementBody periods={financials.annual} />
        </section>
      )}
      {financials.quarterly.length > 0 && (
        <section>
          <h3 className="mb-3 text-xs font-medium tracking-wide text-muted">
            Quarterly
          </h3>
          <StatementBody periods={financials.quarterly} />
        </section>
      )}
      {financials.annual.length === 0 && financials.quarterly.length === 0 && (
        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
          No statements filed.
        </p>
      )}
    </div>
  );
}