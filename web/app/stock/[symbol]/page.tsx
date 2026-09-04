"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import { apiFetch } from "@/lib/api";
import { SectionShell } from "@/components/stock/SectionShell";
import { StatementsTable } from "@/components/stock/StatementsTable";

export default function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const upper = symbol.toUpperCase();

  const { data, isLoading } = useQuery({
    queryKey: ["analysis", upper],
    queryFn: () => apiFetch<any>(`/research/${upper}`),
    // Poll while any section is still building.
    refetchInterval: (q) =>
      q.state.data?.fundamentals?.state === "pending" ? 5000 : false,
  });

  return (
    <div className="px-8 py-6">
      <header className="mb-8">
        <h1 className="font-mono text-2xl text-content">{upper}</h1>
        <p className="mt-1 text-sm text-muted">
          {data?.name ?? (isLoading ? "Loading" : "")}
          {data?.exchange ? ` \u00b7 ${data.exchange}` : ""}
          {data?.is_etf ? " \u00b7 ETF" : ""}
        </p>
      </header>

      <SectionShell
        title="Financial statements"
        state={data?.fundamentals?.state ?? "pending"}
        reason={data?.fundamentals?.reason}
      >
        {data?.fundamentals?.data && (
          <StatementsTable financials={data.fundamentals.data} />
        )}
      </SectionShell>
    </div>
  );
}