"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { kindWord, reasonWords, sentSentence } from "@/features/market/market";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { OrderListResponse, OrderSizing, OrderSummary } from "./types";

type Filter = "working" | "all" | "rejected";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "working", label: "Working" },
  { value: "all", label: "All" },
  { value: "rejected", label: "Rejected" },
];

const EMPTY_TEXT: Record<Filter, string> = {
  working: "No working orders.",
  all: "No orders.",
  rejected: "No rejected orders.",
};

const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  submitted: "Submitted",
  filled: "Filled",
  partial: "Partial",
  cancelled: "Cancelled",
  rejected: "Rejected",
};

const STRATEGY: Record<string, string> = {
  cash_secured_put: "cash-secured put",
  covered_call: "covered call",
  roll: "roll",
};

const CAP = 200;
const isClaude = (kind: string) => kind === "claude_cut" || kind === "claude_cut_unapplied";
const price = (v: number | null) =>
  v === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : `$${v.toFixed(2)}`;

/** What shaped an order's size, in words. Claude's cut is the flag tone and its reason is labelled
 *  as Claude's; a rule's reason has its codes spelled out. */
function Sizing({ a }: { a: OrderSizing }) {
  const claude = isClaude(a.kind);
  return (
    <div className="mt-1 text-[0.8125rem]">
      <StatusWord tone={claude ? "flag" : "neutral"}>{kindWord(a.kind)}</StatusWord> <span>{sentSentence(a)}</span>
      {a.reason && (
        <p className="text-muted">
          {claude ? "Claude's reason: " : "Rule: "}
          {claude ? a.reason : reasonWords(a.reason)}
        </p>
      )}
    </div>
  );
}

function Row({ o }: { o: OrderSummary }) {
  const strike = `$${o.strike.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  return (
    <li className="border-t border-border py-[11px] first:border-t-0">
      <div className="text-sm">
        <span className="font-bold">{o.underlying}</span>{" "}
        <span className="font-bold">
          {strike} {STRATEGY[o.strategy] ?? o.strategy.replace(/_/g, " ")}
        </span>
        <span className="ml-1.5 align-[1px]">
          <StatusWord tone={o.state === "partial" ? "flag" : "neutral"}>{STATE_LABEL[o.state] ?? o.state}</StatusWord>
        </span>
        <div className="text-[0.8125rem] text-muted">
          {whenET(o.created_at)} · {o.is_live ? "live" : "paper"}
        </div>
        <div className="tabular font-mono text-xs text-muted">
          limit {price(o.limit_price)} · filled {o.filled_qty.toFixed(0)} · avg fill {price(o.avg_fill_price)}
        </div>
        {o.detail && <p className="mt-0.5 text-[0.8125rem] text-muted">{o.detail}</p>}
        {(o.sizing ?? []).map((a, i) => (
          <Sizing key={i} a={a} />
        ))}
      </div>
    </li>
  );
}

/**
 * The system's own orders for the wheel. A window (`days`) narrows All and Rejected; Working is
 * never windowed, so an order stuck for weeks cannot be hidden by it. Credit spreads record filled
 * orders only, so they appear under Fills.
 */
export function OrdersTable({ days }: { days?: number } = {}) {
  const [filter, setFilter] = useState<Filter>("working");
  const windowDays = filter === "working" ? undefined : days;
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "orders", filter, windowDays ?? null],
    queryFn: () =>
      apiFetch<OrderListResponse>(
        `/options/orders?state=${filter}${windowDays ? `&days=${windowDays}` : ""}&limit=${CAP}`,
      ),
    placeholderData: (prev) => prev,
  });
  const orders = data?.orders ?? [];

  return (
    <div className="grid gap-3">
      <SegmentedControl label="Filter orders" appearance="chips" options={FILTERS} value={filter} onChange={setFilter} />
      {isLoading ? (
        <p className="text-sm text-muted">Loading orders</p>
      ) : isError ? (
        <p className="text-sm text-muted">Could not load orders</p>
      ) : orders.length === 0 ? (
        <EmptyState text={EMPTY_TEXT[filter]} />
      ) : (
        <ul>
          {orders.map((o) => (
            <Row key={o.id} o={o} />
          ))}
        </ul>
      )}
      {orders.length >= CAP && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {CAP} orders. Choose a shorter window to see every order in it.
        </p>
      )}
      {filter === "working" && (
        <p className="text-[0.8125rem] text-muted">
          A working order is cancelled in IBKR for now. The web cannot cancel one yet.
        </p>
      )}
    </div>
  );
}
