"use client";

import { use } from "react";
import { LedgerShell } from "@/components/ledger/LedgerShell";
import { TickerView } from "@/components/ledger/TickerView";

export default function LedgerTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return (
    <LedgerShell>
      <TickerView symbol={symbol} />
    </LedgerShell>
  );
}
