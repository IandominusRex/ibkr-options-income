"use client";

import { use } from "react";
import { NewsTicker } from "@/components/news/NewsTicker";

export default function NewsTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <NewsTicker symbol={symbol} />;
}
