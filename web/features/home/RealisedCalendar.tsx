"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Sheet } from "@/components/ui/Sheet";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { apiFetch } from "@/lib/api";
import { cellFigure, currentMonth, dayLabel, monthTitle, monthWeeks, shiftMonth } from "./calendar";
import { tradeTitle } from "./trades";
import type { CalendarDay, DayTradesResponse, MonthCalendar, RealisedCalendarResponse } from "./types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const EARLIEST_BACK = 24; // months of history the arrows walk through

const tone = (v: number) => (v > 0 ? "text-gain" : v < 0 ? "text-loss" : "text-muted");

/**
 * What closed on one day. `valueDay` is the value book's part of that day's total, when it had a
 * sale: the calendar's whole-account figure includes it, so it is named apart here, never left
 * silently inside the options total.
 */
function DayCloses({ date, valueDay, onLeave }: { date: string; valueDay?: CalendarDay; onLeave: () => void }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "day", "all", date],
    queryFn: () => apiFetch<DayTradesResponse>(`/pnl/day?date=${date}&strategy=all`),
  });
  const closes = (data?.trades ?? []).filter((t) => t.action !== "opened");
  return (
    <section aria-label={`What closed on ${dayLabel(date)}`} className="mt-4 border-t-2 border-dashed border-perforation pt-3">
      <h3 className="text-[0.8125rem] font-semibold text-muted">{dayLabel(date)}</h3>
      {valueDay && (
        <p className="mt-2 flex items-baseline justify-between gap-3 text-sm">
          <span>Of this day&apos;s total, the value book</span>
          <span className={clsx("tabular font-semibold", tone(valueDay.realized))}>
            {formatStubValue(valueDay.realized, "signed-money")}
          </span>
        </p>
      )}
      {isError && !data ? (
        <p className="mt-2 text-sm text-muted">That day's closes could not be loaded.</p>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading that day's closes" className="mt-2 h-12 rounded-xl bg-sunk" />
      ) : closes.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Nothing closed on this day.</p>
      ) : (
        <ul className="mt-1">
          {closes.map((t) => (
            <li key={t.key} className="grid grid-cols-[1fr_auto] gap-x-3 border-t border-border py-2.5 text-sm first:border-t-0">
              <div className="min-w-0">
                {t.kind === "value" && <div className="text-xs font-bold uppercase tracking-[0.04em] text-muted">Value book</div>}
                <span className="font-bold">{tradeTitle(t)}</span>
                {t.reason && <div className="text-[0.8125rem] text-muted">{t.reason}</div>}
              </div>
              <span className={clsx("tabular text-right font-semibold", t.net_pnl !== null && tone(t.net_pnl), t.net_pnl === null && "hatch text-unknown")}>
                {formatStubValue(t.net_pnl, "signed-money")}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Link
        href={`/trades?view=history&day=${date}`}
        onClick={onLeave}
        className="mt-2 inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold underline-offset-2 hover:underline"
      >
        Open this day in History <ChevronRight size={14} aria-hidden="true" />
      </Link>
    </section>
  );
}

function Grid({
  cal,
  month,
  today,
  valueByDate,
  selected,
  onSelect,
}: {
  cal: MonthCalendar;
  month: string;
  today: string;
  /** The value book's part of each day that had a sale (from the value-only calendar). */
  valueByDate: Map<string, CalendarDay>;
  selected: string | null;
  onSelect: (d: string | null) => void;
}) {
  const byDate = new Map(cal.days.map((d) => [d.date, d]));
  return (
    <table className="mt-3 w-full table-fixed border-separate border-spacing-x-0.5 border-spacing-y-1">
      <caption className="sr-only">{`Realised P&L by day, ${monthTitle(month)}`}</caption>
      <thead>
        <tr>
          {WEEKDAYS.map((d) => (
            <th key={d} scope="col" className="pb-1 text-center text-xs font-semibold text-muted">
              {d}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {monthWeeks(month).map((week, i) => (
          <tr key={i}>
            {week.map((cell, j) => {
              if (cell === null) return <td key={j} />;
              const day = byDate.get(cell.date);
              const isToday = cell.date === today;
              const num = (
                <span className={clsx("text-xs", isToday ? "font-extrabold text-content underline underline-offset-2" : "text-muted")}>
                  {cell.day}
                </span>
              );
              if (!day) {
                return (
                  <td key={j} className="h-[52px] align-top">
                    <div className="px-1 pt-1">{num}</div>
                  </td>
                );
              }
              const on = selected === cell.date;
              const book = valueByDate.get(cell.date);
              return (
                <td key={j} className="h-[52px] align-top">
                  <button
                    type="button"
                    aria-pressed={on}
                    aria-label={`${dayLabel(cell.date)}: ${formatStubValue(day.realized, "signed-money")} realised from ${day.n_closed} close${day.n_closed === 1 ? "" : "s"}${book ? `, of which the value book ${formatStubValue(book.realized, "signed-money")}` : ""}`}
                    onClick={() => onSelect(on ? null : cell.date)}
                    className={clsx(
                      "flex h-[52px] w-full flex-col items-start rounded-xl px-1 pt-1 text-left",
                      // No fill at rest: gain and loss colours on pressed sage measure under 4.5:1 at 12px,
                      // on white they clear 5.3:1. Hover is a ring, selected is the ink fill.
                      on ? "bg-content" : "hover:ring-1 hover:ring-control",
                    )}
                  >
                    <span className={clsx("text-xs", on ? "text-background" : isToday ? "font-extrabold text-content underline underline-offset-2" : "text-muted")}>
                      {cell.day}
                    </span>
                    {/* The sign is in the figure; selected swaps to paper-on-ink, so colour is never the signal. */}
                    <span className={clsx("tabular mt-auto w-full overflow-hidden pb-1 text-center text-xs font-bold", on ? "text-background" : tone(day.realized))}>
                      {cellFigure(day.realized)}
                    </span>
                  </button>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CalendarBody({ now, onLeave }: { now?: Date; onLeave: () => void }) {
  const thisMonth = currentMonth(now);
  const [month, setMonth] = useState(thisMonth);
  const [selected, setSelected] = useState<string | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["pnl", "calendar", month],
    queryFn: () => apiFetch<RealisedCalendarResponse>(`/pnl/calendar?month=${month}`),
  });
  // The value book's part of the month, from the value-only calendar: the whole calendar above
  // includes its sales, and nothing in it tells them apart. A response that is not the value-only
  // one is not taken for it.
  const valueQ = useQuery({
    queryKey: ["pnl", "calendar", month, "value"],
    queryFn: () => apiFetch<RealisedCalendarResponse>(`/pnl/calendar?month=${month}&strategy=value`),
  });
  const valueCal = valueQ.data?.calendar.strategy === "value" ? valueQ.data.calendar : null;
  const valueByDate = new Map((valueCal?.days ?? []).map((d) => [d.date, d]));
  const valueOut = data?.value_available === false;
  const go = (by: number) => {
    setSelected(null);
    setMonth((m) => shiftMonth(m, by));
  };
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(now ?? new Date());
  const cal = data?.calendar;
  const name = monthTitle(month).split(" ")[0];

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          aria-label="Previous month"
          disabled={month <= shiftMonth(thisMonth, -EARLIEST_BACK)}
          onClick={() => go(-1)}
          className="grid h-11 w-11 place-items-center rounded-full text-content hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent"
        >
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <h3 aria-live="polite" className="text-[1.0625rem] font-bold">
          {monthTitle(month)}
        </h3>
        <button
          type="button"
          aria-label="Next month"
          disabled={month >= thisMonth}
          onClick={() => go(1)}
          className="grid h-11 w-11 place-items-center rounded-full text-content hover:bg-sunk disabled:text-muted disabled:hover:bg-transparent"
        >
          <ChevronRight size={20} aria-hidden="true" />
        </button>
      </div>

      {isError && !data ? (
        <p className="mt-4 text-sm text-muted">The calendar could not be loaded. Close this and try again in a moment.</p>
      ) : !cal ? (
        <div role="status" aria-busy="true" aria-label="Loading the calendar" className="mt-3 h-[300px] rounded-xl bg-sunk" />
      ) : (
        <>
          <div className="mt-2">
            <p className="text-[0.8125rem] text-muted">Realised in {name}</p>
            {cal.n_closed === 0 ? (
              <p className="mt-0.5 text-sm">Nothing closed in {name}.</p>
            ) : (
              <>
                <p className={clsx("tabular text-[1.5rem] font-extrabold leading-tight", tone(cal.total))}>
                  {formatStubValue(cal.total, "signed-money")}
                </p>
                <p className="text-[0.8125rem] text-muted">
                  from {cal.n_closed} close{cal.n_closed === 1 ? "" : "s"}
                </p>
              </>
            )}
            {valueCal && valueCal.n_closed > 0 && (
              <p className="tabular mt-0.5 text-[0.8125rem] text-muted">
                Includes the value book: {formatStubValue(valueCal.total, "signed-money")} from {valueCal.n_closed} sale
                {valueCal.n_closed === 1 ? "" : "s"}
              </p>
            )}
          </div>
          <Grid cal={cal} month={month} today={today} valueByDate={valueByDate} selected={selected} onSelect={setSelected} />
          {selected && <DayCloses date={selected} valueDay={valueByDate.get(selected)} onLeave={onLeave} />}
          <div className="mt-4 grid gap-2 text-[0.8125rem] text-muted">
            {!cal.complete && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusWord tone="flag">Commissions incomplete</StatusWord>
                <span>Some closes have no commission recorded yet, so those days are a little too high.</span>
              </p>
            )}
            {valueOut && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusWord tone="flag">Value book unavailable</StatusWord>
                <span>The value book could not be read, so its sales are not counted.</span>
              </p>
            )}
            {data?.spreads_available === false && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <StatusWord tone="flag">Spreads unavailable</StatusWord>
                <span>Credit spreads could not be read, so they are not counted.</span>
              </p>
            )}
            <p>
              Each day is what closed that day, after commissions: options and credit spreads. Share sales are not included, and a day nothing closed is blank.
              The one exception is the value book: its sales count on the day they fill, and a tapped day names them apart.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The calendar button at the end of the chart's range row, and the sheet it opens: each day's
 * realised P&L, a month at a time, as brokerages show it. A day with closes can be tapped to see
 * what closed. The whole account, never scoped by the strategy switcher (the hero is account-wide).
 */
export function RealisedCalendarButton({ now }: { now?: Date }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-label="Daily realised P&L calendar"
        title="Daily realised P&L"
        onClick={() => setOpen(true)}
        className="grid h-11 w-11 place-items-center rounded-full text-muted hover:bg-sunk hover:text-content md:h-9 md:w-9"
      >
        <CalendarDays size={20} aria-hidden="true" />
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Realised P&L">
        <CalendarBody now={now} onLeave={() => setOpen(false)} />
      </Sheet>
    </>
  );
}
