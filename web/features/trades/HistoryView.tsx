"use client";

import clsx from "clsx";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";
import { DecideControls } from "@/components/options/DecideControls";
import type { ApprovalListResponse, ApprovalSummary, OrderListResponse, OrderSummary } from "@/components/options/types";
import { useControls } from "@/components/shell/BotCard";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusWord, type StatusTone } from "@/components/ui/StatusWord";
import { usePendingApprovals } from "@/features/home/NeedsYou";
import { HeldBack } from "@/features/market/HeldBack";
import { proposalTitle } from "@/features/home/ProposalCard";
import { TradeCard } from "@/features/home/TradeCard";
import type { DayTradesResponse } from "@/features/home/types";
import { apiFetch } from "@/lib/api";
import type { CommandStatus } from "@/lib/commands";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { STRATEGY_EYEBROW, type StrategyFilter, kindOf, matchesFilter } from "@/lib/strategy";
import { IN_FLIGHT_STATES, notTradedRows, orderContract } from "./history";
import { dayLabel, shiftDay, timeET } from "./time";

const H2 = "mb-2.5 text-[0.8125rem] font-semibold text-muted";

// State is never colour alone: a word on every row; a flag fill only where it needs attention.
const ORDER_STATE: Record<string, { word: string; tone: StatusTone }> = {
  queued: { word: "Queued", tone: "neutral" },
  submitted: { word: "Submitted", tone: "neutral" },
  partial: { word: "Partial", tone: "flag" },
};

/** Working orders. The key the legacy OrdersTable used, so DecideControls' invalidation reaches it. */
export function useWorkingOrders() {
  return useQuery({
    queryKey: ["options", "orders", "working"],
    queryFn: () => apiFetch<OrderListResponse>("/options/orders?state=working"),
    placeholderData: (prev) => prev,
    refetchInterval: 15_000,
  });
}

function inScope(orders: OrderSummary[], strategy: StrategyFilter): OrderSummary[] {
  // An order carries a strategy name but no right, so a roll order can only be placed under All.
  return orders.filter((o) => IN_FLIGHT_STATES.has(o.state) && matchesFilter(kindOf(o.strategy, null), strategy));
}

/** Approvals still pending on the server whose Approve this browser has sent. */
function useSent(strategy: StrategyFilter, submitted: Map<number, CommandStatus>) {
  const { data, visible } = usePendingApprovals(strategy);
  return { loaded: data !== undefined, sent: visible.filter((a) => submitted.has(a.id)) };
}

/** History's chip count: sent approvals plus working orders in scope; null until both load. */
export function useInFlightCount(strategy: StrategyFilter, submitted: Map<number, CommandStatus>): number | null {
  const { loaded, sent } = useSent(strategy, submitted);
  const orders = useWorkingOrders();
  if (!loaded || !orders.data) return null;
  return sent.length + inScope(orders.data.orders, strategy).length;
}

function SentCard({
  approval,
  command,
  drainHealthy,
  onSettled,
}: {
  approval: ApprovalSummary;
  command: CommandStatus | null;
  drainHealthy: boolean;
  onSettled: (id: number) => void;
}) {
  const titleId = useId();
  const kind = kindOf(approval.strategy, approval.right);
  const eyebrow = approval.source === "roll" ? "Roll" : kind ? STRATEGY_EYEBROW[kind] : approval.strategy;
  return (
    <Card as="article" aria-labelledby={titleId}>
      <span className="text-xs font-bold uppercase tracking-[0.04em] text-muted">{eyebrow} · sent</span>
      <h3 id={titleId} className="mt-1 text-[1.0625rem] font-extrabold tracking-[-0.01em]">
        {proposalTitle(approval)}
      </h3>
      <p className="mt-1 text-sm text-muted">You approved this. The receipt says what the trading service has done with it.</p>
      <div className="mt-3">
        {/* The unchanged decide flow: with a command in flight it shows the receipt, not live buttons. */}
        <DecideControls approval={approval} drainHealthy={drainHealthy} initialCommand={command} onApprovalSettled={onSettled} />
      </div>
      <Link
        href={`/trades/${approval.id}`}
        aria-describedby={titleId}
        className="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content transition-transform duration-[90ms] hover:bg-sunk-deep motion-safe:active:scale-[0.98]"
      >
        Details
      </Link>
    </Card>
  );
}

function Price({ value }: { value: number | null }) {
  if (value == null) return <span className="hatch text-unknown">{UNKNOWN}</span>;
  return <span>${value.toFixed(2)}</span>;
}

function OrderRow({ o }: { o: OrderSummary }) {
  const state = ORDER_STATE[o.state] ?? { word: o.state, tone: "neutral" as const };
  const body = (
    <>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <span className="font-bold">{o.underlying}</span>
          <span className="font-bold">{orderContract(o)}</span>
          <StatusWord tone={state.tone}>{state.word}</StatusWord>
        </p>
        <p className="tabular mt-0.5 font-mono text-[0.8125rem] text-muted">
          limit <Price value={o.limit_price} /> · {o.filled_qty.toFixed(0)} filled · since {timeET(o.created_at)} ·{" "}
          {o.is_live ? "live" : "paper"}
        </p>
        {o.detail && <p className="mt-0.5 text-[0.8125rem]">{o.detail}</p>}
      </div>
    </>
  );
  return (
    <li className="border-t border-border first:border-t-0">
      {o.approval_id !== null ? (
        <Link href={`/trades/${o.approval_id}`} className="-mx-2 grid grid-cols-[1fr_16px] items-center gap-x-2.5 rounded-xl px-2 py-[11px] text-sm hover:bg-sunk">
          {body}
          <ChevronRight size={16} aria-hidden="true" className="text-muted" />
        </Link>
      ) : (
        <div className="py-[11px] text-sm">{body}</div>
      )}
    </li>
  );
}

function InFlight({
  strategy,
  submitted,
  onSettled,
}: {
  strategy: StrategyFilter;
  submitted: Map<number, CommandStatus>;
  onSettled: (id: number) => void;
}) {
  const { loaded, sent } = useSent(strategy, submitted);
  const orders = useWorkingOrders();
  const controls = useControls();
  const drainHealthy = controls.data?.drain_healthy ?? true;
  const working = orders.data ? inScope(orders.data.orders, strategy) : [];
  if (!loaded || !orders.data || (sent.length === 0 && working.length === 0)) return null;
  return (
    <section aria-labelledby="flight-title">
      <h2 id="flight-title" className={H2}>
        In flight
      </h2>
      <div className="grid gap-4">
        {sent.length > 0 && (
          <div className="grid items-start gap-4 lg:grid-cols-2">
            {sent.map((a) => (
              <SentCard key={a.id} approval={a} command={submitted.get(a.id) ?? null} drainHealthy={drainHealthy} onSettled={onSettled} />
            ))}
          </div>
        )}
        {working.length > 0 && (
          <Card as="div">
            <ul>
              {working.map((o) => (
                <OrderRow key={o.id} o={o} />
              ))}
            </ul>
            <p className="mt-2 text-[0.8125rem] text-muted">
              A working order is cancelled in IBKR for now. Cancelling it from here is planned.
            </p>
          </Card>
        )}
      </div>
    </section>
  );
}

function NotTraded({ strategy, day }: { strategy: StrategyFilter; day: string }) {
  // The approvals route filters by UTC date; ask for the day either side and keep New York's day.
  const since = shiftDay(day, -1);
  const until = shiftDay(day, 1);
  const q = useQuery({
    queryKey: ["options", "approvals", "range", since, until],
    queryFn: () =>
      apiFetch<ApprovalListResponse>(`/options/approvals?status=all&since=${since}&until=${until}&limit=200`),
    refetchInterval: 60_000,
  });
  if (!q.data) return null;
  const rows = notTradedRows(q.data.approvals, day, strategy);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="not-traded-title">
      <h2 id="not-traded-title" className={H2}>
        Not traded
      </h2>
      <Card as="div">
        <ul>
          {rows.map((r) => (
            <li key={r.id} className="border-t border-border first:border-t-0">
              <Link
                href={`/trades/${r.id}`}
                className="-mx-2 grid grid-cols-[1fr_auto_16px] items-center gap-x-2.5 rounded-xl px-2 py-[11px] text-sm hover:bg-sunk"
              >
                <div className="min-w-0">
                  <span className="font-bold">{r.title}</span>
                  <span className="ml-1.5 align-[1px]">
                    <StatusWord>{r.word}</StatusWord>
                  </span>
                  <div className="text-[0.8125rem] text-muted">
                    {r.decision} · {r.raised}
                  </div>
                </div>
                <div className="tabular text-right font-semibold">
                  <span className={clsx(r.value === null && "hatch text-unknown")}>
                    {r.value === null ? UNKNOWN : formatMoneyCell(r.value)}
                  </span>
                  <div className="text-[0.8125rem] font-normal text-muted">{r.valueLabel}</div>
                </div>
                <ChevronRight size={16} aria-hidden="true" className="text-muted" />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

/**
 * One New York day of the wheel: what is in flight (today only), what traded (Home's trade cards),
 * and what was proposed and did not trade. Read-only, apart from the unchanged decide flow inside
 * a sent card's receipt.
 */
export function HistoryView({
  strategy,
  day,
  today,
  onDay,
  submitted,
  onSettled,
}: {
  strategy: StrategyFilter;
  /** The New York day shown, YYYY-MM-DD. */
  day: string;
  today: string;
  /** null goes back to today. */
  onDay: (day: string | null) => void;
  submitted: Map<number, CommandStatus>;
  onSettled: (id: number) => void;
}) {
  const isToday = day === today;
  const q = useQuery({
    queryKey: ["pnl", "day", strategy, day],
    queryFn: () => apiFetch<DayTradesResponse>(`/pnl/day?date=${day}&strategy=${strategy}`),
    refetchInterval: isToday ? 60_000 : false,
  });
  const trades = (q.data?.trades ?? []).filter((t) => t.source === "wheel");
  // The day the next arrow goes to; null is today (the URL carries no day for it).
  const later = q.data?.next_day;
  const nextDay = later && later < today ? later : null;

  let traded: ReactNode;
  if (q.isError && !q.data) {
    traded = <p className="text-sm text-muted">This day's trades could not be loaded. They are asked for again every minute.</p>;
  } else if (!q.data) {
    traded = <div className="h-32 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading the day's trades" />;
  } else if (trades.length === 0) {
    traded = <p className="text-sm text-muted">{isToday ? "Nothing has traded yet today." : `Nothing traded on ${dayLabel(day)}.`}</p>;
  } else {
    traded = (
      <div className="grid items-start gap-4 lg:grid-cols-2">
        {trades.map((t) => (
          <TradeCard key={t.key} trade={t} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-[1.0625rem] font-bold">
          {dayLabel(day)}
          {isToday ? " · today" : ""}
        </h2>
        {/* Left of the arrows, so showing or hiding it never moves them. */}
        {!isToday && (
          <Button variant="secondary" onClick={() => onDay(null)}>
            Today
          </Button>
        )}
        <Button
          variant="quiet"
          aria-label="Previous day with trades"
          disabled={!q.data?.previous_day}
          onClick={() => q.data?.previous_day && onDay(q.data.previous_day)}
        >
          <ChevronLeft size={18} aria-hidden="true" />
        </Button>
        {/* From a past day, next is the following day with trades, or today when none is left. */}
        <Button
          variant="quiet"
          aria-label={isToday || nextDay ? "Next day with trades" : "Back to today"}
          disabled={isToday}
          onClick={() => onDay(nextDay)}
        >
          <ChevronRight size={18} aria-hidden="true" />
        </Button>
      </div>

      {isToday && <InFlight strategy={strategy} submitted={submitted} onSettled={onSettled} />}

      <section aria-labelledby="traded-title">
        <h2 id="traded-title" className={H2}>
          Traded
        </h2>
        {traded}
      </section>

      <HeldBack day={day} strategy={strategy} isToday={isToday} />

      <NotTraded strategy={strategy} day={day} />

      {strategy === "all" && (
        <p className="text-[0.8125rem] text-muted">
          Credit spreads trade on their own and are not listed here. Their days are under{" "}
          <Link href="/trades?strategy=spread" className="font-semibold text-content underline underline-offset-2">
            Credit spreads
          </Link>
          .
        </p>
      )}
    </div>
  );
}
