"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import type { ComponentProps, JSXElementConstructor, ReactNode } from "react";
import { ChecksSection } from "@/components/checks/ChecksSection";
import { RefreshButton } from "@/components/shell/RefreshButton";
import { NewsPanel } from "@/components/stock/NewsPanel";
import { PriceChart } from "@/components/stock/PriceChart";
import { SentimentPanel } from "@/components/stock/SentimentPanel";
import { StatementsTable } from "@/components/stock/StatementsTable";
import { SummaryPanel } from "@/components/stock/SummaryPanel";
import { TechnicalsPanel } from "@/components/stock/TechnicalsPanel";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { NameNotes } from "@/features/market/NameNotes";
import { ValueBlock } from "@/features/stock-value/ValueBlock";
import type { ValueTicker } from "@/features/stock-value/types";
import { ApiError, apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { StockSection } from "./StockSection";
import { nameLine, valueLeads, valueLines, type Analysis } from "./stock";

// The generated types mark a nullable field optional; the panels' own types read it as a value or
// null. The API always sends the key (pydantic writes None as null), so the shapes agree at runtime.
type Props<C extends JSXElementConstructor<any>> = ComponentProps<C>;

const PENDING_SECTIONS = ["fundamentals", "technicals", "sentiment", "news", "checks"] as const;

function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">{children}</div>;
}

function BackLink() {
  return (
    <Link
      href="/research"
      className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
    >
      <ChevronLeft size={16} aria-hidden="true" />
      Research
    </Link>
  );
}

/** The last quote under the name: the price, "Delayed" in words when it is stale, and its age. */
function QuoteLine({ quote }: { quote: Analysis["quote"] }) {
  if (quote?.value == null) {
    return (
      <p className="mt-2 text-sm">
        Last price <span className="hatch px-1 text-unknown">n/a</span>
      </p>
    );
  }
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
      <span className="tabular text-[1.5rem] font-extrabold tracking-[-0.015em]">{formatMoneyCell(quote.value)}</span>
      {quote.stale && <StatusWord tone="flag">Delayed</StatusWord>}
      <span className="text-[0.8125rem] text-muted">{relativeAge(quote.as_of)}</span>
    </p>
  );
}

/**
 * The stock page (web overhaul Part 5): a back link to Research, the ticker as the title with its name
 * and last price, then two columns from 1024px. Left: the price chart with the value book's levels
 * drawn across it, the value block (first when the book would buy the name at a price or holds it,
 * else at the foot of the column), Checks, Technicals and the financial statements (behind a
 * disclosure). Right: the news service's notes, News, Sentiment and a model's written summary. The
 * DOM order is the phone order. The page reads; its only command is the value block's "Run Claude's
 * analysis".
 */
export function StockPage({ symbol }: { symbol: string }) {
  const upper = symbol.toUpperCase();
  const { data, isError, error } = useQuery({
    queryKey: ["analysis", upper],
    queryFn: () => apiFetch<Analysis>(`/research/${upper}`),
    // Look again while any section is still being built.
    refetchInterval: (q) => (PENDING_SECTIONS.some((s) => q.state.data?.[s]?.state === "pending") ? 5000 : false),
    // A name the research service does not know will not appear in a minute; the rest are worth a retry.
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
  });
  // The value block reads the same request under the same key, so this costs no second fetch.
  const { data: value } = useQuery({
    queryKey: ["value", "ticker", upper],
    queryFn: () => apiFetch<ValueTicker>(`/value/${upper}`),
  });
  const leads = valueLeads(value);

  const header = (
    <header className="mt-1 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">{upper}</h1>
        <p className="mt-1 text-sm text-muted">{data ? nameLine(data) : isError ? "" : "Loading"}</p>
        {data && <QuoteLine quote={data.quote} />}
      </div>
      <RefreshButton label={`Refresh ${upper}`} className="-mr-2 -mt-1" />
    </header>
  );

  if (isError && !data) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <Shell>
        <BackLink />
        {header}
        <p className="mt-3 text-sm">
          {missing
            ? `The research service does not know ${upper}. Check the ticker, or add it to the watchlist on Research.`
            : "This page could not be loaded. It tries again when you reopen it."}
        </p>
      </Shell>
    );
  }

  const section = (key: (typeof PENDING_SECTIONS)[number]) => ({
    state: data?.[key]?.state ?? "pending",
    reason: data?.[key]?.reason ?? null,
  });
  const valueBlock = <ValueBlock symbol={upper} />;

  return (
    <Shell>
      <BackLink />
      {header}
      <div className="mt-4 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 grid-cols-1 gap-4">
          <section aria-labelledby="stock-chart-title">
            <h2 id="stock-chart-title" className="sr-only">
              {`${upper} price chart`}
            </h2>
            <PriceChart symbol={upper} lines={valueLines(value)} />
          </section>
          {leads && valueBlock}
          <StockSection id="checks" title="Checks" {...section("checks")}>
            {data?.checks?.data && <ChecksSection data={data.checks.data as Props<typeof ChecksSection>["data"]} />}
          </StockSection>
          <StockSection id="technicals" title="Technicals" {...section("technicals")}>
            {data?.technicals?.data && <TechnicalsPanel data={data.technicals.data as Props<typeof TechnicalsPanel>["data"]} />}
          </StockSection>
          <StockSection id="statements" title="Financial statements" {...section("fundamentals")}>
            {data?.fundamentals?.data && (
              <Disclosure summary={<span className="text-sm font-semibold">Revenue, profit, balance sheet and cash flow, as filed</span>}>
                <StatementsTable financials={data.fundamentals.data as Props<typeof StatementsTable>["financials"]} />
              </Disclosure>
            )}
          </StockSection>
          {!leads && valueBlock}
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-4">
          <NameNotes symbol={upper} />
          <StockSection id="news" title="News" {...section("news")}>
            {data?.news?.data && <NewsPanel items={data.news.data as Props<typeof NewsPanel>["items"]} />}
          </StockSection>
          <StockSection id="sentiment" title="Sentiment" {...section("sentiment")}>
            {data?.sentiment?.data && <SentimentPanel data={data.sentiment.data as Props<typeof SentimentPanel>["data"]} />}
          </StockSection>
          <StockSection id="summary" title="Model summary" state="ready">
            <SummaryPanel symbol={upper} />
          </StockSection>
        </div>
      </div>
    </Shell>
  );
}
