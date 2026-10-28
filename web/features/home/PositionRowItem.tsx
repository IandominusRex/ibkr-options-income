import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { NameFlags } from "@/features/market/NameFlags";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import type { PositionRow } from "./positions";

/**
 * One position row, as Home's Positions card and the Portfolio page draw it: the title bold with
 * its status words, a muted sub-line (and an optional figure line beneath it), the value at the
 * right with its label, and a chevron when the whole row opens the contract's page. `flags` puts
 * the name's "Weak health" and "Event" words beside the title; a card that shows them in its own
 * header turns it off.
 */
export function PositionRowItem({
  row: r,
  flags = true,
  detail,
}: {
  row: PositionRow;
  flags?: boolean;
  detail?: ReactNode;
}) {
  const pnl = r.valueLabel === "open P&L";
  const body = (
    <>
      <div className="min-w-0">
        <span className="font-bold">{r.title}</span>
        {r.status && (
          <span className="ml-1.5 align-[1px]">
            <StatusWord tone={r.status.tone}>{r.status.word}</StatusWord>
          </span>
        )}
        {r.alert && (
          <span className="ml-1.5 align-[1px]">
            <StatusWord tone="flag">Roll alert</StatusWord>
          </span>
        )}
        {flags && r.underlying && <NameFlags symbol={r.underlying} />}
        <div className="text-[0.8125rem] text-muted">{r.sub}</div>
        {detail && <div className="tabular font-mono text-xs text-muted">{detail}</div>}
      </div>
      <div className="tabular text-right font-semibold">
        <span
          className={clsx(
            r.value === null && "hatch text-unknown",
            r.value !== null && pnl && r.value < 0 && "text-loss",
            r.value !== null && pnl && r.value > 0 && "text-gain",
          )}
        >
          {r.value === null ? UNKNOWN : pnl ? formatStubValue(r.value, "signed-money") : formatMoneyCell(r.value)}
        </span>
        <div className="text-[0.8125rem] font-normal text-muted">{r.valueLabel}</div>
      </div>
    </>
  );
  return (
    <li className="border-t border-border first:border-t-0">
      {r.href ? (
        // The whole row opens the contract. The chevron says so without a word.
        <Link
          href={r.href}
          className="-mx-2 grid grid-cols-[1fr_auto_16px] items-center gap-x-2.5 rounded-xl px-2 py-[11px] text-sm hover:bg-sunk"
        >
          {body}
          <ChevronRight size={16} aria-hidden="true" className="text-muted" />
        </Link>
      ) : (
        <div className="grid grid-cols-[1fr_auto] gap-x-2.5 py-[11px] text-sm">{body}</div>
      )}
    </li>
  );
}
