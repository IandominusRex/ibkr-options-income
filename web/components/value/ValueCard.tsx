"use client";

import type { ReactNode } from "react";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub } from "@/components/ui/Stub";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import type { StrategyFilter } from "@/lib/strategy";
import { useValueBook } from "./useValueBook";
import { ceilingSum, listWords, nextExitWords, sharesWord } from "./format";
import type { ValueBook, ValueBreakers, ValuePosition } from "./types";
import { ValueProposalRow } from "./ValueProposalRow";

/** The strategy filters the card shows under: the whole account, and the value book on its own. */
function shownUnder(strategy: StrategyFilter): boolean {
  return strategy === "all" || strategy === "value";
}

function Hatched({ children }: { children: ReactNode }) {
  return <span className="hatch px-1 text-unknown">{children}</span>;
}

function Breakers({ b }: { b: ValueBreakers }) {
  const lines: ReactNode[] = [];
  if (b.trend === true) {
    lines.push(
      <p key="trend" className="flex flex-wrap items-center gap-2 text-sm">
        <StatusWord tone="flag">Trend brake on</StatusWord>
        <span>The market is under its 10-month average: no new entries, and the ceiling is smaller.</span>
      </p>,
    );
  } else if (b.trend === null || b.trend === undefined) {
    lines.push(
      <p key="trend" className="text-sm">
        <span className="hatch px-1 text-unknown">Trend brake n/a</span>
      </p>,
    );
  }
  if (b.drawdown === true) {
    lines.push(
      <p key="dd" className="flex flex-wrap items-center gap-2 text-sm">
        <StatusWord tone="flag">Drawdown stop on</StatusWord>
        <span>
          {b.drawdown_pct == null
            ? "The book is below its high, so new entries have stopped."
            : `The book is ${b.drawdown_pct.toFixed(1)}% below its high, so new entries have stopped.`}
        </span>
      </p>,
    );
  } else if (b.drawdown === null || b.drawdown === undefined) {
    lines.push(
      <p key="dd" className="text-sm">
        <span className="hatch px-1 text-unknown">Drawdown stop n/a</span>
      </p>,
    );
  }
  if (b.trim_offered && !b.trimmed) {
    lines.push(
      <p key="trim" className="flex flex-wrap items-center gap-2 text-sm">
        <StatusWord tone="flag">Trim offered</StatusWord>
        <span>Trim to half is offered in Telegram.</span>
      </p>,
    );
  }
  if (lines.length === 0) {
    return <p className="mt-2 text-[0.8125rem] text-muted">No breaker is on.</p>;
  }
  return <div className="mt-2 grid gap-1.5">{lines}</div>;
}

function PositionRow({ p }: { p: ValuePosition }) {
  const exit = nextExitWords(p.next_exit);
  const value = p.mark == null ? null : p.mark * p.shares;
  return (
    <li className="border-t border-border first:border-t-0">
      <div className="grid grid-cols-[1fr_auto] gap-x-2.5 py-[11px] text-sm">
        <div className="min-w-0">
          <span className="font-bold">{p.symbol}</span>
          <div className="text-[0.8125rem] text-muted">
            {listWords(p.list_name)} · {sharesWord(p.shares)}
            {p.avg_cost != null && ` · average cost ${formatMoneyCell(p.avg_cost)}`}
          </div>
          <div className="text-[0.8125rem] text-muted">
            {exit ?? (
              <>
                Next exit: <Hatched>n/a</Hatched>
              </>
            )}
          </div>
        </div>
        <div className="tabular text-right font-semibold">
          <span className={value === null ? "hatch text-unknown" : undefined}>
            {value === null ? UNKNOWN : formatMoneyCell(value)}
          </span>
          <div className="text-[0.8125rem] font-normal text-muted">value</div>
        </div>
      </div>
    </li>
  );
}

function Body({ book }: { book: ValueBook }) {
  const positions = book.positions ?? [];
  const proposals = book.proposals ?? [];
  const firstWaiting = proposals.find((p) => p.needs_tap && p.status === "pending");
  const funding = book.funding ?? [];
  const room =
    book.ceiling_usd == null || book.used_usd == null ? null : Math.max(0, book.ceiling_usd - book.used_usd);
  return (
    <>
      {!book.enabled && (
        <p className="mt-2 text-sm">The value book is off. It places nothing while it is off.</p>
      )}
      <Stub
        label="Value book ceiling"
        lines={[
          { label: "Ceiling", value: book.ceiling_usd ?? null },
          { label: "In use", value: book.used_usd == null ? null : -book.used_usd, format: "signed-money" },
          { label: "Room left", value: room, total: true },
        ]}
      />
      <Breakers b={book.breakers ?? { trim_offered: false, trimmed: false }} />
      {funding.length > 0 && (
        <ul className="mt-2 grid gap-1">
          {funding.map((f) => (
            <li key={f.id} className="text-sm">
              {f.symbol} is waiting for {formatMoneyCell(f.needed_usd)} of cash.
            </li>
          ))}
        </ul>
      )}
      {positions.length === 0 && proposals.length === 0 ? (
        <p className="mt-3 border-t border-border pt-3 text-sm text-muted">
          The book holds no shares and has no proposal open.
        </p>
      ) : (
        <>
          {positions.length > 0 && (
            <div className="mt-3 border-t border-border pt-2">
              <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Held</h3>
              <ul>
                {positions.map((p) => (
                  <PositionRow key={p.id} p={p} />
                ))}
              </ul>
            </div>
          )}
          {proposals.length > 0 && (
            <div className="mt-3 border-t border-border pt-2">
              <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Proposals</h3>
              <ul>
                {proposals.map((p) => (
                  <ValueProposalRow
                    key={p.id}
                    proposal={p}
                    releaseMaxCloses={book.release_max_closes}
                    lead={p.id === firstWaiting?.id}
                  />
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Loaded() {
  const { data, isError } = useValueBook();
  if (!data) {
    return isError ? (
      <Card as="div">
        <p className="text-sm text-muted">The value book could not be loaded. It is asked for again every minute.</p>
      </Card>
    ) : (
      <div role="status" aria-busy="true" aria-label="Loading the value book" className="h-28 rounded-[18px] bg-surface" />
    );
  }
  return (
    <Card aria-labelledby="value-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="value-title" className="text-[1.0625rem] font-bold">
          Value book
        </h2>
        {data.available && (
          <span className="tabular text-[0.8125rem] text-muted">
            {data.ceiling_usd == null || data.used_usd == null ? (
              <>
                <Hatched>n/a</Hatched> ceiling
              </>
            ) : (
              `${ceilingSum(data.used_usd, data.ceiling_usd)} in use`
            )}
          </span>
        )}
      </div>
      {data.available ? (
        <Body book={data} />
      ) : (
        <p className="mt-2 text-sm">The value book has not written anything yet.</p>
      )}
    </Card>
  );
}

/**
 * The value book on Home: what it may hold, what it holds and the next exit for each name, the
 * breakers in words, and its open proposals with Review where one waits on a tap. Every figure is
 * Python's; the decide flow is <ValueDecide/>. A trim has no button here (plan ruling 10): it lives
 * on the Telegram card.
 */
export function ValueCard({ strategy }: { strategy: StrategyFilter }) {
  if (!shownUnder(strategy)) return null;
  return <Loaded />;
}
