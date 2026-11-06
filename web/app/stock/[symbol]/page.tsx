"use client";

import { use } from "react";
import { StockPage } from "@/features/stock/StockPage";

export default function Page({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <StockPage symbol={symbol} />;
}
