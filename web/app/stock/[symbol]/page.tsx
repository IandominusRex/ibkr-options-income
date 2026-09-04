"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { apiFetch } from "@/lib/api";
import { NewsPanel } from "@/components/stock/NewsPanel";
import { PriceChart } from "@/components/stock/PriceChart";
import { SectionShell } from "@/components/stock/SectionShell";
import { SentimentPanel } from "@/components/stock/SentimentPanel";
import { StatementsTable } from "@/components/stock/StatementsTable";
import { TechnicalsPanel } from "@/components/stock/TechnicalsPanel";
import { relativeAge } from "@/lib/format";

const PENDING_SECTIONS = ["fundamentals", "technicals", "sentiment", "news"] as const;

export default function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const upper = symbol.toUpperCase();

  const { data, isLoading } = useQuery({
    queryKey: ["analysis", upper],
    queryFn: () => apiFetch<any>(`/research/${upper}`),
    // Poll while any section is still building \u2014 not just fundamentals, which was the
    // only section that existed before M4 added technicals/sentiment/news.
    refetchInterval: (q) =>
      PENDING_SECTIONS.some((s) => q.state.data?.[s]?.state === "pending") ? 5000 : false,
  });

  const quote = data?.quote;

  return (
    <div className="px-8 py-6">
      <header className="mb-8">
        <h1 className="font-mono text-2xl text-content">{upper}</h1>
        <p className="mt-1 text-sm text-muted">
          {data?.name ?? (isLoading ? "Loading" : "")}
          {data?.exchange ? ` \u00b7 ${data.exchange}` : ""}
          {data?.is_etf ? " \u00b7 ETF" : ""}
        </p>
        {quote?.value != null && (
          <p className="mt-2 flex items-baseline gap-2">
            <span className="tabular text-lg text-content">${quote.value.toFixed(2)}</span>
            <span className={`text-xs ${quote.stale ? "text-unknown" : "text-muted"}`}>
              {relativeAge(quote.as_of)}
              {quote.stale ? " \u00b7 delayed" : ""}
            </span>
          </p>
        )}
      </header>

      <section className="mb-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Price chart</h2>
        <PriceChart symbol={upper} />
      </section>

      <SectionShell
        title="Technicals"
        state={data?.technicals?.state ?? "pending"}
        reason={data?.technicals?.reason}
      >
        {data?.technicals?.data && <TechnicalsPanel data={data.technicals.data} />}
      </SectionShell>

      <SectionShell
        title="Financial statements"
        state={data?.fundamentals?.state ?? "pending"}
        reason={data?.fundamentals?.reason}
      >
        {data?.fundamentals?.data && (
          <StatementsTable financials={data.fundamentals.data} />
        )}
      </SectionShell>

      <SectionShell
        title="Sentiment"
        state={data?.sentiment?.state ?? "pending"}
        reason={data?.sentiment?.reason}
      >
        {data?.sentiment?.data && <SentimentPanel data={data.sentiment.data} />}
      </SectionShell>

      <SectionShell
        title="News"
        state={data?.news?.state ?? "pending"}
        reason={data?.news?.reason}
      >
        {data?.news?.data && <NewsPanel items={data.news.data} />}
      </SectionShell>
    </div>
  );
}