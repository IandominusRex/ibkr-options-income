"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { etLabel, regimeLine, shortDay } from "@/features/claude-context/format";
import type { ClaudeContext, IndexRegime } from "@/features/claude-context/types";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { limitSentence } from "./market";

/** Home shows three stories, News all of them (six at most); Trades is only the regimes. */
export type MarketVariant = "home" | "trades" | "news";
const STORIES: Record<MarketVariant, number> = { home: 3, trades: 0, news: 6 };

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Flags({ ctx }: { ctx: ClaudeContext }) {
  return (
    <>
      {!ctx.regime_enabled && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Off in config</StatusWord>
          <span>The regime limits are switched off, so none of them is applied.</span>
        </p>
      )}
      {ctx.suspended_today && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Suspended today</StatusWord>
          <span>/regime off was sent. The regime limits are not applied today.</span>
        </p>
      )}
      {ctx.claude_cut_breaker_tripped_today && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Cuts paused today</StatusWord>
          <span>Claude&apos;s size cuts are recorded but not applied until tomorrow.</span>
        </p>
      )}
    </>
  );
}

function IndexRow({ ix, ctx }: { ix: IndexRegime; ctx: ClaudeContext }) {
  const applied = ctx.regime_enabled && !ctx.suspended_today;
  const limit = applied ? limitSentence((ctx.limits ?? []).find((l) => l.index === ix.index)) : null;
  return (
    <li>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[1.0625rem] font-bold">{ix.index}</span>
        <StatusWord tone={ix.effective === "normal" ? "neutral" : "flag"}>{cap(ix.effective)}</StatusWord>
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">
        {regimeLine(ix)}
        {limit && ` ${limit}`}
      </p>
    </li>
  );
}

function Stories({ ctx, count, describe }: { ctx: ClaudeContext; count: number; describe: boolean }) {
  const picture = ctx.picture ?? null;
  if (!ctx.available) {
    return <p className="mt-3 text-sm">The news service has not written anything yet, so there is no market picture.</p>;
  }
  if (!picture) return <p className="mt-3 text-sm">No market picture has been built yet.</p>;
  const stories = (picture.stories ?? []).slice(0, count);
  return (
    <div className="mt-3 border-t border-border pt-3">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Stories in the market picture</h3>
      {picture.stale && (
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Stale</StatusWord>
          <span>Stale since {etLabel(picture.built_at)}. Claude&apos;s step failed on the last rebuild.</span>
        </p>
      )}
      {stories.length === 0 ? (
        <p className="mt-1 text-sm">No stories are being tracked.</p>
      ) : (
        <ul className="mt-1 grid gap-1.5">
          {stories.map((s) => (
            <li key={s.id} className="break-words text-sm">
              <span className="font-bold">{s.title}</span>{" "}
              <span className="text-[0.8125rem] text-muted">since {shortDay(s.started_on)}</span>
              {describe && s.description && (
                <span className="mt-0.5 block text-[0.8125rem]">
                  <span className="mr-1.5 text-xs font-semibold tracking-[0.04em] text-muted">Claude&apos;s description</span>
                  {s.description}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {!picture.stale && <p className="mt-1.5 text-[0.8125rem] text-muted">Rebuilt {etLabel(picture.built_at)}</p>}
    </div>
  );
}

/** What the news service triaged in the last seven days: judged as noise, not reviewed, promoted. */
function Triage({ ctx }: { ctx: ClaudeContext }) {
  const promoted = (ctx.dropped ?? []).filter((d) => d.promoted).length;
  return (
    <p className="mt-3 text-[0.8125rem] text-muted">
      Last 7 days: {ctx.dropped_total ?? 0} stories judged as noise by Claude
      {promoted > 0 ? ` (${promoted} promoted after the market moved)` : ""}, {ctx.not_reviewed_7d ?? 0} not reviewed.
    </p>
  );
}

/**
 * The market in one card: the SPY and QQQ regimes as words with what each does to new puts, the
 * flags that change what happens today, and (Home, News) the market picture's stories. Read-only;
 * the numbers are Python's and the descriptions are labelled as Claude's. The full page is
 * What Claude knows.
 */
export function MarketCard({ variant }: { variant: MarketVariant }) {
  const { data, isError } = useClaudeContext();
  if (!data) {
    return isError ? (
      <Card as="div">
        <p className="text-sm text-muted">The market picture could not be loaded. It is asked for again every minute.</p>
      </Card>
    ) : (
      <div role="status" aria-busy="true" aria-label="Loading the market" className="h-28 rounded-[18px] bg-surface" />
    );
  }
  const titleId = `market-title-${variant}`;
  const count = STORIES[variant];
  return (
    <Card aria-labelledby={titleId}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id={titleId} className="text-[1.0625rem] font-bold">
          Market
        </h2>
        {data.regime && <span className="text-[0.8125rem] text-muted">Recorded {etLabel(data.regime.as_of)}</span>}
      </div>
      <Flags ctx={data} />
      {data.regime ? (
        <ul className="mt-3 grid gap-3 sm:grid-cols-2">
          {[data.regime.spy, data.regime.qqq].map((ix) => (
            <IndexRow key={ix.index} ix={ix} ctx={data} />
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm">
          <span className="hatch px-1.5 text-unknown">n/a</span> No regime recorded yet. The trading service writes one on its
          first scan.
        </p>
      )}
      {count > 0 && <Stories ctx={data} count={count} describe={variant === "news"} />}
      {variant === "news" && data.available && <Triage ctx={data} />}
      <Link
        href="/more/claude"
        className="mt-3 inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-content underline underline-offset-2 md:min-h-8"
      >
        What Claude knows
        <ChevronRight size={14} aria-hidden="true" />
      </Link>
    </Card>
  );
}
