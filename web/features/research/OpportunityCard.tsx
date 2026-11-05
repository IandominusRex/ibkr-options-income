import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { price } from "@/components/value/format";
import { Hatched } from "@/features/stock-value/parts";
import { PriceBar } from "./PriceBar";
import { ageWords, assessedHref, fractionPct, layoutBar, listWords, reasonSentence, stockValueHref, verdictWords } from "./format";
import type { TopItem } from "./types";

// A link to another page, drawn like the console's secondary button. Never lime: it acts on nothing.
const LINK =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[0.9375rem] font-bold text-content hover:bg-sunk-deep";

/**
 * One name on a Top opportunities list. It reads and links; it sends nothing. "Buy shares" goes to
 * the stock page's value block, where the book's own decide flow lives; the put link goes to the
 * name's passed cash-secured puts in Trades, and exists only when the parent found one.
 */
export function OpportunityCard({ item, canSellPut }: { item: TopItem; canSellPut: boolean }) {
  const titleId = `opp-${item.list_name}-${item.symbol}`;
  const unknown = layoutBar(item).unknown;
  const age = ageWords(item.age_days);
  const ready = item.verdict === "READY";
  const showPut = canSellPut && item.put_ceiling != null;
  const reasons = (item.reasons ?? []).slice(0, 3);

  return (
    <Card as="article" aria-labelledby={titleId} className="flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-[1.0625rem] font-bold">
            {item.symbol}
          </h3>
          <p className="text-xs text-muted">{listWords(item.list_name)}</p>
        </div>
        <StatusWord>{verdictWords(item.verdict)}</StatusWord>
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">
        {item.decided_by === "claude" ? "Claude's verdict decides this. Python's gates still apply." : "Python only"}
      </p>

      <PriceBar item={item} />
      {unknown.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Not on the bar: {unknown.join(", ")} <Hatched>n/a</Hatched>
        </p>
      )}

      <dl className="mt-3">
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <dt className="text-muted">Margin of safety</dt>
          <dd className="tabular font-semibold">{item.mos == null ? <Hatched>n/a</Hatched> : fractionPct(item.mos)}</dd>
        </div>
      </dl>

      {reasons.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold tracking-[0.04em] text-muted">Python&apos;s reasons</h4>
          <ul className="mt-1 grid gap-1 text-sm">
            {reasons.map((r) => (
              <li key={r}>{reasonSentence(r)}</li>
            ))}
          </ul>
        </div>
      )}

      {(ready || showPut) && (
        <div className="mt-4 flex flex-wrap gap-2">
          {ready && (
            <Link href={stockValueHref(item.symbol)} className={LINK}>
              Buy shares
            </Link>
          )}
          {showPut && (
            <Link href={assessedHref(item.symbol)} className={LINK}>
              Sell a put up to {price(item.put_ceiling)}
            </Link>
          )}
        </div>
      )}

      <p className="tabular mt-auto pt-3 text-xs text-muted">{age ?? <>Scorecard <Hatched>n/a</Hatched></>}</p>
    </Card>
  );
}
