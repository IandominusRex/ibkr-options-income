"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { apiFetch } from "@/lib/api";
import { BusinessBlock } from "./BusinessBlock";
import { ClaudeBlock } from "./ClaudeBlock";
import {
  decidedByWords,
  fileAgeWords,
  fractionPct,
  listWords,
  planChangeWords,
  planSegments,
  price,
  readShort,
  readWords,
  refetchMs,
  shortDate,
  triggerWords,
  verdictWords,
} from "./format";
import { Segments } from "./parts";
import { SizeBlock } from "./SizeBlock";
import type { Segment, ValueFile, ValueList, ValueReevaluation, ValueTicker, Watch } from "./types";
import { WorthBlock } from "./WorthBlock";

function Verdict({ l, file }: { l: ValueList; file: ValueFile }) {
  const parts: Segment[] = [
    l.effective_fair_value == null ? { text: "Fair value n/a", unknown: true } : { text: `Fair value ${price(l.effective_fair_value)}` },
    file.price == null ? { text: "price n/a", unknown: true } : { text: `price ${price(file.price)}` },
    l.mos == null ? { text: "margin of safety n/a", unknown: true } : { text: `margin of safety ${fractionPct(l.mos)}` },
  ];
  return (
    <div role="group" aria-label={listWords(l.list_name)} className="border-t border-border py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="text-sm font-bold">{listWords(l.list_name)}</span>
        <StatusWord>{verdictWords(l.verdict)}</StatusWord>
        <span className="text-[0.8125rem] text-muted">{decidedByWords(l)}</span>
      </div>
      <p className="tabular mt-1 text-sm">
        <Segments parts={parts} />
      </p>
    </div>
  );
}

function Reevaluations({ items }: { items: ValueReevaluation[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="vb-reeval" className="mt-4 border-t border-border pt-3">
      <h3 id="vb-reeval" className="text-sm font-bold">
        Re-evaluations
      </h3>
      <ul aria-label="Re-evaluations" className="mt-1">
        {items.map((r) => {
          const change = planChangeWords(r);
          return (
            <li key={r.id} className="border-t border-border py-2 first:border-t-0 text-sm">
              <span className="tabular font-semibold">{shortDate(r.session)}</span>
              <span className="ml-2 text-muted">{listWords(r.list_name)}</span>
              <span className="ml-2">
                <StatusWord tone={r.severity === "major" ? "flag" : "neutral"}>
                  {r.severity === "major" ? "Major" : "Minor"}
                </StatusWord>
              </span>
              <div className="text-[0.8125rem]">{triggerWords(r.triggers) || "No trigger recorded."}</div>
              <div className="tabular text-[0.8125rem] text-muted">
                <Segments parts={[change]} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Body({ sym, t, onQueued }: { sym: string; t: ValueTicker; onQueued: () => void }) {
  const file = t.file;
  if (!file) {
    return (
      <p className="mt-2 text-sm">
        {t.computed === "pending"
          ? "The scorecard is being worked out. It will appear here."
          : `The value book has no scorecard for ${sym} yet.`}
      </p>
    );
  }
  if (file.not_applicable_reason) {
    return <p className="mt-2 text-sm">The value book does not score {sym}: {file.not_applicable_reason}.</p>;
  }
  const lists = file.lists ?? [];
  const plan = planSegments(t.plan);
  const readNote = readWords(t.claude?.read_at, file.as_of);
  return (
    <>
      <div className="mt-1">
        {lists.map((l) => (
          <Verdict key={l.list_name} l={l} file={file} />
        ))}
        {plan ? (
          <p className="tabular mt-1 border-t border-border pt-2 text-sm">
            <span className="text-muted">Plan: </span>
            <Segments parts={plan} />
          </p>
        ) : (
          <p className="mt-1 border-t border-border pt-2 text-[0.8125rem] text-muted">The book holds no shares of {sym}.</p>
        )}
      </div>
      <BusinessBlock file={file} claude={t.claude} />
      <WorthBlock file={file} claude={t.claude} readNote={readShort(t.claude?.read_at)} />
      <SizeBlock file={file} plan={t.plan} />
      <Reevaluations items={t.reevaluations ?? []} />
      <ClaudeBlock symbol={sym} claude={t.claude} readNote={readNote} onQueued={onQueued} />
    </>
  );
}

/**
 * The value book's view of one name, on the stock page (value book Part 6, spec section 10): the verdict
 * first, then the three questions (is the business still doing its job, what is it worth, how much and
 * when), a held name's re-evaluations, and what Claude wrote with the button that asks for a fresh read.
 * One self-contained card, mounted with one line, so the Research part can move or restyle it. It
 * reads `GET /value/{symbol}` and writes nothing but the one command in <AnalyseButton/>.
 */
export function ValueBlock({ symbol }: { symbol: string }) {
  const sym = symbol.toUpperCase();
  const [watch, setWatch] = useState<Watch | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["value", "ticker", sym],
    queryFn: () => apiFetch<ValueTicker>(`/value/${sym}`),
    // As the page's other sections: look again while the file is still being worked out; also
    // for a few minutes after a Claude read is queued.
    refetchInterval: (q) => refetchMs(q.state.data, watch, Date.now()),
  });
  const titleId = `value-block-${sym}`;
  if (!data) {
    return isError ? (
      <div className="mt-4">
        <Card as="div">
          <p className="text-sm text-muted">The value book&apos;s view of {sym} could not be loaded.</p>
        </Card>
      </div>
    ) : (
      <div
        role="status"
        aria-busy="true"
        aria-label="Loading the value book's view"
        className="mt-4 h-28 rounded-[18px] bg-surface"
      />
    );
  }
  return (
    <div className="mt-4">
      <Card aria-labelledby={titleId}>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <h2 id={titleId} className="text-[1.0625rem] font-bold">
            Value book on {sym}
          </h2>
          {data.available && (
            <span className="tabular text-[0.8125rem] text-muted">{fileAgeWords(data, data.file?.as_of)}</span>
          )}
        </div>
        {data.available ? (
          <Body
            sym={sym}
            t={data}
            onQueued={() => setWatch({ since: Date.now(), readAt: data.claude?.read_at ?? null })}
          />
        ) : (
          <p className="mt-2 text-sm">The value book has not written anything yet.</p>
        )}
      </Card>
    </div>
  );
}
