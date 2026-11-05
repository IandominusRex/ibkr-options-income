"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { StatusWord } from "@/components/ui/StatusWord";
import { UNKNOWN } from "@/lib/format";
import { causeWords, expiresWords, listWords, price, proposalTitle, reasonWords, sharesWord } from "./format";
import type { ValueProposal } from "./types";
import { ValueDecide } from "./ValueDecide";

const capitalise = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** Who decided it and where it stands, in words. A tap-waiting proposal has Review instead. */
function standing(p: ValueProposal): { word: string; text: string } | null {
  if (p.needs_tap && p.status === "pending") return null;
  const who = p.needs_tap ? "Approved by your tap" : "Approved by the system";
  if (p.status === "funding") return { word: "Waiting for cash", text: who };
  if (p.status === "sent") return { word: "Order sent", text: who };
  return { word: "Approved", text: who };
}

/** One of the book's open proposals: the trade, why, and Review when it waits on you. */
export function ValueProposalRow({ proposal: p, releaseMaxCloses }: { proposal: ValueProposal; releaseMaxCloses: number }) {
  const [open, setOpen] = useState(false);
  const state = standing(p);
  const title = proposalTitle(p);
  return (
    <li className="border-t border-border py-[11px] first:border-t-0">
      <div className="grid grid-cols-[1fr_auto] items-start gap-x-2.5 text-sm">
        <div className="min-w-0">
          <span className="font-bold">{title}</span>
          <div className="text-[0.8125rem] text-muted">
            {listWords(p.list_name)} · {reasonWords(p.reason)}
          </div>
          <div className="text-[0.8125rem] text-muted">{causeWords(p)}</div>
        </div>
        <div className="tabular text-right font-semibold">
          {p.kind === "buy" ? (
            <>
              <span className={p.cost_usd == null ? "hatch text-unknown" : undefined}>
                {p.cost_usd == null ? UNKNOWN : price(p.cost_usd)}
              </span>
              <div className="text-[0.8125rem] font-normal text-muted">cost</div>
            </>
          ) : (
            <div className="text-[0.8125rem] font-normal text-muted">sells at the next check</div>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {state ? (
          <>
            <StatusWord>{state.word}</StatusWord>
            <span className="text-[0.8125rem]">{state.text}</span>
          </>
        ) : (
          <>
            <Button variant="primary" aria-haspopup="dialog" onClick={() => setOpen(true)}>
              Review
            </Button>
            <span className="text-[0.8125rem] text-muted">{expiresWords(p.expires_at)}</span>
          </>
        )}
      </div>
      <Sheet open={open} onClose={() => setOpen(false)} title="Review value trade">
        <h3 className="text-[1.0625rem] font-extrabold">{title}</h3>
        <p className="mt-2 text-sm">
          {p.kind === "buy"
            ? `The book proposes buying ${sharesWord(p.shares)} of ${p.symbol}${p.price == null ? "" : `, sized at the close of ${price(p.price)}`}.`
            : `The book proposes selling ${sharesWord(p.shares)} of ${p.symbol}.`}
        </p>
        <p className="mt-2 text-sm">{causeWords(p)}</p>
        <p className="mt-2 text-sm text-muted">Why: {reasonWords(p.reason)}.</p>
        <p className="mt-1 text-sm text-muted">{capitalise(expiresWords(p.expires_at))}.</p>
        <ValueDecide proposal={p} releaseMaxCloses={releaseMaxCloses} />
      </Sheet>
    </li>
  );
}
