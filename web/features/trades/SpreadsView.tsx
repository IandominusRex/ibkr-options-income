"use client";

import clsx from "clsx";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import type { SpreadPosition } from "@/features/home/types";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { BOOK_LABEL, bookRow, breakEven, dayLabel, itemDetail, itemLabel, itemOutcome, pickSentence, pickTitle, timeET } from "./spreads";
import { todayInNewYork } from "./time";
import type { SpreadMenuItem, SpreadPick, SpreadPicksResponse } from "./types";

const H2 = "mb-2.5 text-[0.8125rem] font-semibold text-muted";

/**
 * Read-only: one New York day of the spreads books, trades first. Each paper spread carries the
 * menu Claude saw, collapsed, as its reason; picks with no spread here follow. Nothing here sends anything.
 */
export function SpreadsView() {
  // null is "today", the server's New York day; a past day is a fixed date that does not change.
  const [day, setDay] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["spreads", "picks", day ?? "today"],
    queryFn: () => apiFetch<SpreadPicksResponse>(day === null ? "/spreads/picks" : `/spreads/picks?day=${day}`),
    refetchInterval: day === null ? 60_000 : false,
  });
  const data = q.data;
  // The day the next arrow goes to; null is today (the request carries no day for it).
  const nextDay = data?.next_day && data.next_day < todayInNewYork() ? data.next_day : null;

  if (q.isError && !data) {
    return <p className="text-sm text-muted">The spreads picks could not be loaded right now.</p>;
  }
  if (!data) {
    return <div className="h-40 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading the spreads picks" />;
  }

  // A pick belongs under its spread when that spread is on this page; every other pick is "other".
  const shown = new Set(data.positions.map((p) => p.spread_id));
  const pickFor = new Map(data.picks.filter((p) => p.spread_id && shown.has(p.spread_id)).map((p) => [p.spread_id as string, p]));
  const others = data.picks.filter((p) => !(p.spread_id && shown.has(p.spread_id)));

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-[1.0625rem] font-bold">
          {dayLabel(data.day)}
          {day === null ? " · today" : ""}
        </h2>
        {/* Left of the arrows, so showing or hiding it never moves them. */}
        {day !== null && (
          <Button variant="secondary" onClick={() => setDay(null)}>
            Today
          </Button>
        )}
        <Button
          variant="quiet"
          aria-label="Previous day with spreads activity"
          disabled={data.previous_day === null}
          onClick={() => setDay(data.previous_day)}
        >
          <ChevronLeft size={18} aria-hidden="true" />
        </Button>
        {/* From a past day, next is the following day with activity, or today when none is left. */}
        <Button
          variant="quiet"
          aria-label={day === null || nextDay !== null ? "Next day with spreads activity" : "Back to today"}
          disabled={day === null}
          onClick={() => setDay(nextDay)}
        >
          <ChevronRight size={18} aria-hidden="true" />
        </Button>
      </div>

      {!data.available ? (
        <p className="text-sm text-muted">The spreads book could not be read right now.</p>
      ) : (
        <>
          {!data.ai_enabled && (
            <p className="text-sm text-muted">
              Claude&apos;s picker is off, so the spreads service sells its own pick without a menu. Menus appear here when the picker is on.
            </p>
          )}
          <Books positions={data.positions} underlying={data.underlying} pickFor={pickFor} />
          {others.length > 0 && (
            <section aria-labelledby="other-picks-title">
              <h2 id="other-picks-title" className={H2}>
                Other picks
              </h2>
              <div className="grid items-start gap-4 lg:grid-cols-2">
                {others.map((p) => (
                  <PickCard key={p.pick_id} pick={p} underlying={data.underlying} />
                ))}
              </div>
            </section>
          )}
          {data.ai_enabled && data.picks.length === 0 && <p className="text-sm text-muted">No menu was offered on this day.</p>}
        </>
      )}
    </div>
  );
}

function Books({
  positions,
  underlying,
  pickFor,
}: {
  positions: SpreadPosition[];
  underlying: string;
  pickFor: Map<string, SpreadPick>;
}) {
  const of = (mode: string) => positions.filter((p) => p.mode === mode);
  const other = positions.filter((p) => !(p.mode in BOOK_LABEL));
  return (
    <section aria-labelledby="book-title">
      <h2 id="book-title" className={H2}>
        Spreads opened this day
      </h2>
      {positions.length === 0 ? (
        <p className="text-sm text-muted">No spread was opened on this day.</p>
      ) : (
        <div className="grid gap-4">
          {/* Paper beside baseline: Claude's pick against the rules' pick, the baseline book's purpose. */}
          <div className="grid items-start gap-4 lg:grid-cols-2">
            {of("paper").length > 0 && <Book label={BOOK_LABEL.paper} rows={of("paper")} underlying={underlying} pickFor={pickFor} />}
            {of("baseline").length > 0 && <Book label={BOOK_LABEL.baseline} rows={of("baseline")} underlying={underlying} pickFor={pickFor} />}
          </div>
          {of("shadow").length > 0 && <Book label={BOOK_LABEL.shadow} rows={of("shadow")} underlying={underlying} pickFor={pickFor} />}
          {other.length > 0 && <Book label="Other books" rows={other} underlying={underlying} pickFor={pickFor} />}
        </div>
      )}
    </section>
  );
}

function Book({
  label,
  rows,
  underlying,
  pickFor,
}: {
  label: string;
  rows: SpreadPosition[];
  underlying: string;
  pickFor: Map<string, SpreadPick>;
}) {
  const titleId = useId();
  return (
    <Card as="section" aria-labelledby={titleId}>
      <h3 id={titleId} className="text-[1.0625rem] font-bold">
        {label}
      </h3>
      <ul className="mt-1">
        {rows.map((p) => {
          const r = bookRow(p, underlying);
          const pick = p.mode === "paper" ? pickFor.get(p.spread_id) : undefined;
          const body: ReactNode = (
            <>
              <div className="min-w-0">
                <span className="font-bold">{r.title}</span>
                <span className="ml-1.5 align-[1px]">
                  <StatusWord>{r.word}</StatusWord>
                </span>
                <div className="text-[0.8125rem] text-muted">{r.sub}</div>
              </div>
              <div className="tabular text-right font-semibold">
                <span
                  className={clsx(
                    r.value === null && "hatch text-unknown",
                    r.signed && r.value !== null && r.value < 0 && "text-loss",
                    r.signed && r.value !== null && r.value > 0 && "text-gain",
                  )}
                >
                  {r.value === null ? UNKNOWN : r.signed ? formatStubValue(r.value, "signed-money") : formatMoneyCell(r.value)}
                </span>
                <div className="text-[0.8125rem] font-normal text-muted">{r.valueLabel}</div>
              </div>
            </>
          );
          return (
            <li key={r.key} className="border-t border-border first:border-t-0">
              {r.href ? (
                <Link href={r.href} className="-mx-2 grid grid-cols-[1fr_auto_16px] items-center gap-x-2.5 rounded-xl px-2 py-[11px] text-sm hover:bg-sunk">
                  {body}
                  <ChevronRight size={16} aria-hidden="true" className="text-muted" />
                </Link>
              ) : (
                <div className="grid grid-cols-[1fr_auto] items-center gap-x-2.5 py-[11px] text-sm">{body}</div>
              )}
              {pick && (
                <div className="mb-3">
                  <MenuDisclosure pick={pick} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** The menu Claude saw, collapsed: what was sent, Claude's reason (labelled), the lettered menu. */
function MenuDisclosure({ pick, withSentence = true }: { pick: SpreadPick; withSentence?: boolean }) {
  return (
    <Disclosure
      summary={
        <span className="text-[0.8125rem] font-bold">
          The menu Claude saw{" "}
          <span className="font-medium text-muted">
            · {pick.choice === "skip" ? "Claude skipped" : `Claude picked ${pick.choice}`} at {timeET(pick.created_at)}
          </span>
        </span>
      }
    >
      {withSentence && <p className="text-[0.8125rem]">{pickSentence(pick)}</p>}
      {pick.reason.trim() !== "" && (
        <p className="mt-2 text-[0.8125rem]">
          <span className="font-bold">Claude&apos;s view:</span> {pick.reason}
        </p>
      )}
      {pick.menu_readable ? (
        <ul aria-label="Menu" className="mt-3 border-t-2 border-dashed border-perforation pt-1">
          {pick.menu.map((i) => (
            <MenuRow key={i.letter} item={i} pick={pick} />
          ))}
        </ul>
      ) : (
        <UnreadableMenu className="mt-3" />
      )}
      <p className="mt-1 text-xs text-muted">
        Asked {pick.model} · gamma {pick.regime}
        {pick.event_flag ? " · event day" : ""}
      </p>
    </Disclosure>
  );
}

/**
 * A stored menu that no longer parses. The unknown texture is a small mark beside the words, never
 * over them: hatching the whole sentence drew same-coloured lines through every letter.
 */
function UnreadableMenu({ className }: { className?: string }) {
  return (
    <p className={clsx("border-t-2 border-dashed border-perforation pt-2 text-[0.8125rem]", className)}>
      <span aria-hidden="true" className="hatch mr-2 inline-block h-3 w-6 rounded-[6px] align-middle" />
      <span className="text-unknown">This menu could not be read.</span>
    </p>
  );
}

function PickCard({ pick, underlying }: { pick: SpreadPick; underlying: string }) {
  const titleId = useId();
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-[0.04em] text-muted">
          Credit spread · {pick.side ? `${pick.side} side` : "menu"}
        </span>
        <span className="text-[0.8125rem] text-muted">{timeET(pick.created_at)}</span>
      </div>
      <h3 id={titleId} className="mt-1 text-[1.0625rem] font-extrabold tracking-[-0.01em]">
        {pickTitle(pick, underlying)}
      </h3>
      <p className="mt-2 text-sm">{pickSentence(pick)}</p>
      <div className="mt-3">
        {pick.menu_readable ? (
          <MenuDisclosure pick={pick} withSentence={false} />
        ) : (
          <UnreadableMenu />
        )}
      </div>
    </Card>
  );
}

function MenuRow({ item, pick }: { item: SpreadMenuItem; pick: SpreadPick }) {
  const be = breakEven(item);
  const outcome = itemOutcome(pick, item.letter);
  return (
    <li className="grid grid-cols-[28px_1fr_auto] items-start gap-x-2.5 border-t border-border py-2.5 first:border-t-0">
      <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-full bg-sunk font-mono text-[0.8125rem] font-semibold">
        {item.letter}
      </span>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm">
          <span className="font-bold">
            <span className="sr-only">{item.letter}: </span>
            {itemLabel(item)}
          </span>
          {item.position === "baseline" && <StatusWord>Baseline</StatusWord>}
          {pick.choice === item.letter && <StatusWord>Claude&apos;s pick</StatusWord>}
          {outcome && <StatusWord>{outcome.word}</StatusWord>}
        </p>
        {outcome?.why && <p className="mt-0.5 text-[0.8125rem]">Did not trade: {outcome.why}.</p>}
        <p className="mt-0.5 text-[0.8125rem] text-muted">
          {itemDetail(item)} ·{" "}
          {be === null ? (
            <>
              break-even <span className="hatch text-unknown">{UNKNOWN}</span>
            </>
          ) : (
            be
          )}
        </p>
      </div>
      <div className="text-right">
        <p className="tabular font-mono text-[0.84375rem] font-medium">${item.credit_mid.toFixed(2)}</p>
        <p className="text-xs text-muted">credit a share</p>
      </div>
    </li>
  );
}
