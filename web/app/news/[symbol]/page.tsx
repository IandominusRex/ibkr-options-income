"use client";

import { use } from "react";
import { NewsTickerPage } from "@/features/news/NewsTickerPage";
import { decodeSegment } from "@/lib/segment";

export default function Page({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <NewsTickerPage symbol={decodeSegment(symbol)} />;
}
