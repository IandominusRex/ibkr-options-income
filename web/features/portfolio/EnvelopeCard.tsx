"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import type { ReactNode } from "react";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines, type FigureRow } from "@/features/claude-context/FigureLines";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { UNKNOWN } from "@/lib/format";
import { freshnessText } from "@/lib/money";
import { shortDate } from "./format";

type EnvelopeResponse = components["schemas"]["RiskEnvelopeResponse"];
type EnvelopeSnapshot = components["schemas"]["RiskEnvelopeSnapshot"];
type EnvelopeSwitch = components["schemas"]["RiskEnvelopeSwitch"];

const known = (n: number | null | undefined): n is number => typeof n === "number" && Number.isFinite(n);

/** A real minus for a negative figure, as the rest of the console writes signed numbers. */
function body(n: number, digits: number): string {
  const text = Math.abs(n).toFixed(digits);
  return n < 0 && Number(text) !== 0 ? `−${text}` : text;
}

/** A scenario loss as a share of net liquidation. Unknown is the hatched n/a, never 0. */
const pct = (n: number | null | undefined): string => (known(n) ? `${body(n, 1)}%` : UNKNOWN);
/** U_ew is a multiple of net liquidation. */
const times = (n: number | null | undefined): string => (known(n) ? `${body(n, 2)}x` : UNKNOWN);

/** A figure that may be unknown: the value, or a hatched n/a that no colour alone carries. */
function Figure({ text, unknown }: { text: string; unknown: boolean }) {
  return <span className={clsx(unknown && "hatch text-unknown")}>{text}</span>;
}

type Line = { label: string; text: string };

/**
 * One headline measure: its name, the reading large, a flag word when it is past its limit, then
 * the limit today, the target the glide ends at and the reading net of long options, as figure
 * lines under a perforation. A reading we do not have is a hatched n/a, never a zero.
 */
function Measure({
  name,
  hint,
  reading,
  over,
  lines,
}: {
  name: string;
  hint: string;
  reading: { text: string; unknown: boolean };
  over: boolean;
  lines: Line[];
}) {
  return (
    <div role="group" aria-label={name} className="mt-4 min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 className="text-[0.8125rem] font-semibold tracking-[0.02em] text-muted">{name}</h3>
        {over && <StatusWord tone="flag">Over limit</StatusWord>}
      </div>
      <p className="tabular mt-1 text-[1.625rem] font-extrabold leading-none tracking-[-0.02em]">
        <Figure text={reading.text} unknown={reading.unknown} />
      </p>
      <p className="mt-1 text-[0.8125rem] text-muted">{hint}</p>
      <dl className="tabular mt-3 border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium">
        {lines.map((l) => (
          <div key={l.label} className="flex min-h-6 items-baseline justify-between gap-3">
            <dt className="min-w-0 font-sans font-normal">{l.label}</dt>
            <dd className={clsx("text-right", l.text === UNKNOWN && "hatch text-unknown")}>{l.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Gross beside net, one pair per row. Unknown is one hatched n/a for the pair. */
function pair(gross: number | null | undefined, net: number | null | undefined): FigureRow["value"] {
  if (!known(gross) || !known(net)) return UNKNOWN;
  return (
    <>
      <span>{pct(gross)}</span>
      <span className="text-muted"> / </span>
      <span>{pct(net)}</span>
    </>
  );
}

function scenarioRows(s: EnvelopeSnapshot | null): FigureRow[] {
  const rows: [string, number | undefined, number | undefined][] = [
    ["S10 at +10 vol points", s?.s10_vol10, s?.s10_vol10_net],
    ["S20, SPY down 20%", s?.s20, s?.s20_net],
    ["G10, one-day index gap of 10%", s?.g10, s?.g10_net],
    ["P20, index down 20% over 10 sessions", s?.p20, s?.p20_net],
    ["T20, tech names down 20%", s?.t20, s?.t20_net],
    ["S-SMH, SMH down 30%", s?.s_smh, s?.s_smh_net],
  ];
  return rows.map(([label, gross, net]) => {
    const value = pair(gross, net);
    return { label, value, unknown: value === UNKNOWN };
  });
}

/** What each switch is called, and what each value of it means, in words. */
const SWITCH_WORDS: Record<string, { label: string; words: (v: string) => string }> = {
  envelope_enforce: {
    label: "Envelope limits",
    words: (v) => (v === "on" ? "On, blocks new risk past the limits" : v === "record" ? "Recording only" : "Off"),
  },
  spreads_paper: { label: "Spreads paper trading", words: (v) => (v === "on" ? "On" : "Off, shadow only") },
  spxw_ready: {
    label: "SPXW cutover",
    words: (v) => ({ spxw: "Ready for SPXW", xsp: "Ready for XSP", stay: "Stay on SPY" })[v] ?? "Not ready",
  },
  hedge_instrument: { label: "Hedge instrument", words: (v) => (v === "none" ? "None chosen" : v) },
  bridge: { label: "Bridge hedge", words: (v) => ({ on: "On", ended: "Ended" })[v] ?? "Off" },
  tech_cap: { label: "Tech-linked cap", words: onOff },
  stacking_rule: { label: "Stacking rule", words: onOff },
  index_1x: { label: "Index 1x multipliers", words: onOff },
  leveraged_sleeve: { label: "Leveraged sleeve", words: onOff },
  leveraged_cc_auto: { label: "Leveraged covered calls without a tap", words: onOff },
  t20_limit: { label: "T20 as a limit", words: onOff },
  slow_breaker: {
    label: "Slow drawdown breaker",
    words: (v) => (v === "off" ? "Off" : `Trips at ${v}% drawdown`),
  },
  cc_basis_floor: {
    label: "Covered-call floor",
    words: (v) => (v === "1.00" ? "At or above cost basis" : `Down to ${Math.round(Number(v) * 100)}% of cost basis`),
  },
  hedge_monetisation: { label: "Hedge monetisation", words: (v) => (v === "none" ? "None" : `At ${v}`) },
  leveraged_entry: {
    label: "Leveraged entry signal",
    words: (v) => (v === "on" ? "On, acts on the signal" : v === "record" ? "Recording only" : "Off"),
  },
};

function onOff(v: string): string {
  return v === "on" ? "On" : "Off";
}

function switchRow(sw: EnvelopeSwitch): FigureRow {
  const entry = SWITCH_WORDS[sw.name];
  const label = entry?.label ?? sw.name.replaceAll("_", " ");
  const words = entry ? entry.words(sw.value) : sw.value;
  return {
    label,
    value: (
      <>
        {words}
        {sw.source !== "default" && <span className="ml-1.5 font-sans text-xs font-normal text-muted">from {sw.source.split(":")[0]}</span>}
      </>
    ),
  };
}

/** The enforcement word beside the title: what the limits do today, never a colour. */
function EnforceWord({ enforce }: { enforce: string }): ReactNode {
  if (enforce === "on") return <StatusWord tone="neutral">Enforced</StatusWord>;
  if (enforce === "record") return <StatusWord tone="neutral">Not enforced yet</StatusWord>;
  return <StatusWord tone="neutral">Off</StatusWord>;
}

const ENFORCE_SENTENCE: Record<string, string> = {
  on: "New risk that would put the book past a limit is blocked.",
  record: "The book is measured and recorded against the limits. Nothing is blocked yet.",
  off: "The envelope is off: nothing is checked against the limits.",
};

/**
 * The risk envelope: how big a market fall the book can take, against the limit it is gliding to.
 * Display only: it reads `GET /envelope` and writes nothing. Every scenario figure is a percent of
 * net liquidation and every one is Python's, measured gross (no long option helps) and net.
 */
export function EnvelopeCard() {
  const { data, isError } = useQuery({
    queryKey: ["envelope"],
    queryFn: () => apiFetch<EnvelopeResponse>("/envelope"),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });

  if (isError && !data) {
    return (
      <Card aria-labelledby="envelope-title">
        <h2 id="envelope-title" className="text-[1.0625rem] font-bold">
          Risk envelope
        </h2>
        <p className="mt-2 text-sm text-muted">Could not load the risk envelope.</p>
        <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card as="div" className="h-[420px] sm:h-[360px]" role="status" aria-busy="true" aria-label="Loading the risk envelope" />
    );
  }

  const snap = data.snapshot ?? null;
  const s10 = snap?.s10 ?? null;
  const uew = snap?.uew ?? null;
  const s10Limit = data.limits.s10 ?? null;
  const uewLimit = data.limits.uew ?? null;
  const live = snap?.source === "live";
  const glide = data.glide ?? null;
  const cash = data.cash_after_itm_assignment ?? null;
  const t20Limit = data.limits.t20 ?? null;
  const changed = data.switches.filter((s) => s.value !== s.default).length;

  const extra: FigureRow[] = [
    {
      label: "Cash after every ITM put is assigned",
      value: known(cash) ? `$${Math.round(cash).toLocaleString("en-US")}` : UNKNOWN,
      unknown: !known(cash),
    },
  ];
  if (known(t20Limit)) extra.push({ label: "T20 limit", value: pct(t20Limit) });

  return (
    <Card aria-labelledby="envelope-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="envelope-title" className="text-[1.0625rem] font-bold">
            Risk envelope
          </h2>
          <EnforceWord enforce={data.enforce} />
          {snap && !snap.measured && <StatusWord tone="flag">Unmeasured</StatusWord>}
        </div>
        {snap && (
          <span className="text-[0.8125rem] text-muted">
            <span className="font-semibold">{live ? "Live IV" : "Stored IV"}</span> · Measured {freshnessText(snap.captured_at)}
          </span>
        )}
      </div>

      <p className="mt-2 text-sm">{ENFORCE_SENTENCE[data.enforce] ?? ENFORCE_SENTENCE.off}</p>
      {snap ? (
        <p className="mt-1 text-[0.8125rem] text-muted">
          {live
            ? "Option values use live implied volatility."
            : "Option values use the last end-of-day volatility, not live quotes."}
        </p>
      ) : (
        <p className="mt-1 text-[0.8125rem] text-muted">No measurement has been recorded yet.</p>
      )}
      <p className="mt-1 text-[0.8125rem] text-muted">
        {glide ? (
          <>
            <span>{`Glide week ${glide.week} of ${glide.weeks}`}</span>
            <span>{` · ends ${shortDate(glide.end)}`}</span>
          </>
        ) : (
          "Glide not started"
        )}
      </p>
      {snap && !snap.measured && (
        <p className="mt-2 text-sm">
          {snap.unmeasured && snap.unmeasured.length > 0
            ? `Could not value ${snap.unmeasured.join(", ")}, so these figures are incomplete.`
            : "Some of the book could not be valued, so these figures are incomplete."}
          {snap.reasons && snap.reasons.length > 0 && (
            <span className="text-muted">{` Why: ${snap.reasons.join("; ")}.`}</span>
          )}
        </p>
      )}

      <div className="grid gap-x-8 sm:grid-cols-2">
        <Measure
          name="S10 gross"
          hint="Loss if the S&P 500 falls 10%, as a share of net liquidation."
          reading={{ text: pct(s10), unknown: !known(s10) }}
          over={known(s10) && known(s10Limit) && s10 > s10Limit}
          lines={[
            { label: "Limit today", text: pct(s10Limit) },
            { label: "Target", text: pct(data.limits.s10_target) },
            { label: "Net of long options", text: pct(snap?.s10_net) },
          ]}
        />
        <Measure
          name="U_ew"
          hint="Exposure, weighted for leverage, as a multiple of net liquidation."
          reading={{ text: times(uew), unknown: !known(uew) }}
          over={known(uew) && known(uewLimit) && uew > uewLimit}
          lines={[
            { label: "Limit today", text: times(uewLimit) },
            { label: "Target", text: times(data.limits.uew_target) },
          ]}
        />
      </div>

      <FigureLines label="Other scenarios, gross and net of long options" rows={scenarioRows(snap)} />
      <FigureLines label="Cash and limits" rows={extra} />

      <div className="mt-3">
        <Disclosure
          summary={
            <span className="text-sm font-semibold">
              Switches <span className="font-normal text-muted">· {changed} of {data.switches.length} changed from the default</span>
            </span>
          }
        >
          <FigureLines label="Switches" rows={data.switches.map(switchRow)} />
        </Disclosure>
      </div>
    </Card>
  );
}
