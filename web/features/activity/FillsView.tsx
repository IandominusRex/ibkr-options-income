"use client";

import { useState } from "react";
import { FillsTable } from "@/components/options/FillsTable";
import { OrdersTable } from "@/components/options/OrdersTable";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ExecutionsList } from "./ExecutionsList";
import { DEFAULT_WINDOW, WINDOWS, windowLabel } from "./fills";
import { SpreadFills } from "./SpreadFills";

type List = "orders" | "fills" | "ibkr";
const LISTS: { value: List; label: string }[] = [
  { value: "orders", label: "Orders" },
  { value: "fills", label: "Fills" },
  { value: "ibkr", label: "At IBKR" },
];

const SOURCE = "mt-1 text-[0.8125rem] text-muted";

/**
 * Three lists, each headed by whose record it is, and never merged: the system's orders, the
 * system's fills (the wheel, then the credit-spread book), and IBKR's own executions from the
 * ledger. Where they disagree is the finding, so the page does not paper over it. One window
 * (7 days to a year) applies to all of them.
 */
export function FillsView() {
  const [list, setList] = useState<List>("orders");
  const [days, setDays] = useState<number>(DEFAULT_WINDOW);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegmentedControl label="List" appearance="chips" options={LISTS} value={list} onChange={setList} />
        <SegmentedControl
          label="Window"
          appearance="chips"
          options={WINDOWS.map((w) => ({ value: String(w), label: windowLabel(w) }))}
          value={String(days)}
          onChange={(v) => setDays(Number(v))}
        />
      </div>
      {list === "orders" && (
        <Card aria-labelledby="orders-title">
          <h2 id="orders-title" className="text-[1.0625rem] font-bold">
            Orders
          </h2>
          <p className={SOURCE}>
            The system&apos;s record: the wheel orders it sent to IBKR, and how each ended. Credit spreads record filled
            orders only, so they are under Fills.
          </p>
          <div className="mt-3">
            <OrdersTable days={days} />
          </div>
        </Card>
      )}
      {list === "fills" && (
        <>
          <Card aria-labelledby="wheel-fills-title">
            <h2 id="wheel-fills-title" className="text-[1.0625rem] font-bold">
              Wheel
            </h2>
            <p className={SOURCE}>The system&apos;s record: what it saw filled. IBKR&apos;s own list is under At IBKR.</p>
            <div className="mt-3">
              <FillsTable days={days} />
            </div>
          </Card>
          <Card aria-labelledby="spread-fills-title">
            <h2 id="spread-fills-title" className="text-[1.0625rem] font-bold">
              Credit spreads
            </h2>
            <p className={SOURCE}>The system&apos;s record, from the credit-spreads book.</p>
            <div className="mt-3">
              <SpreadFills days={days} />
            </div>
          </Card>
        </>
      )}
      {list === "ibkr" && (
        <Card aria-labelledby="ibkr-title">
          <h2 id="ibkr-title" className="text-[1.0625rem] font-bold">
            Executions at IBKR
          </h2>
          <p className={SOURCE}>
            IBKR&apos;s record: every execution the ledger holds, from the live feed, the Flex query and statement
            imports, in any book. It is not reconciled with the system&apos;s lists here: if they disagree, the
            disagreement is the finding.
          </p>
          <div className="mt-3">
            <ExecutionsList days={days} />
          </div>
        </Card>
      )}
    </div>
  );
}
