import { formatMoneyCell, freshnessText, type MoneyKind, type MoneyProps } from "@/lib/money";

// Rule 3 (web CLAUDE.md / M3 task 3.1): kind is rendered, not implied. "value" is the
// plain, unqualified case (an account total, a market value) and needs no tag; the
// other three carry accounting nuance a reader must not have to infer from context.
const KIND_LABEL: Partial<Record<MoneyKind, string>> = {
  realized: "realized",
  unrealized: "unrealized",
  basis: "basis",
};

/**
 * The money cell. Renders a figure that never lies about what it doesn't know:
 * null/undefined always render `n/a` with `.hatch` texture, never `$0.00` - and a
 * genuine zero always renders `$0`, so the two are never confusable. Colour is never
 * the only signal - a negative figure carries its minus sign in the text, and `kind`
 * renders as a word, not just a class.
 */
export function Money({ value, kind, complete = true, signed = false, asOf }: MoneyProps) {
  const title = asOf !== undefined ? freshnessText(asOf) : undefined;
  const isUnknown = value === null || value === undefined || Number.isNaN(value);

  if (isUnknown) {
    return (
      <span className="tabular hatch text-unknown" data-kind={kind} title={title}>
        {formatMoneyCell(value)}
      </span>
    );
  }

  const negative = value < 0;
  const positive = value > 0;
  const colorClass = negative ? "text-loss" : signed && positive ? "text-gain" : "text-content";
  const prefix = signed && positive ? "+" : "";
  const kindLabel = KIND_LABEL[kind];

  return (
    <span className="tabular" data-kind={kind} title={title}>
      <span className={colorClass}>
        {prefix}
        {formatMoneyCell(value)}
      </span>
      {kindLabel && (
        <span className="ml-1 text-[10px] uppercase tracking-wide text-muted">{kindLabel}</span>
      )}
      {!complete && (
        <span className="ml-1 text-[10px] uppercase tracking-wide text-muted">gross</span>
      )}
    </span>
  );
}
