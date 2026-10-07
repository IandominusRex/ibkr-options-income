"use client";

import { use } from "react";
import { TickerView } from "@/components/ledger/TickerView";

export default function LedgerTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <TickerView symbol={symbol} />;
}
