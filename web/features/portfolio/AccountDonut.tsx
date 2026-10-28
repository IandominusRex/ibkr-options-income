import clsx from "clsx";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { pctLabel, ringFraction } from "./donut";

const SIZE = 200;
const C = SIZE / 2;
// Two concentric rings: buying power used on the outside, cash on the inside.
const OUTER = { r: 91, stroke: 13 };
const INNER = { r: 73, stroke: 10 };

function Ring({ r, stroke, fraction, arc }: { r: number; stroke: number; fraction: number; arc: string }) {
  const length = 2 * Math.PI * r;
  return (
    <>
      <circle cx={C} cy={C} r={r} fill="none" strokeWidth={stroke} className="stroke-sunk" />
      {fraction > 0 && (
        <circle
          cx={C}
          cy={C}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${Math.min(fraction * length, length - 0.01)} ${length}`}
          // Twelve o'clock is the start. Charts do not animate in: a ring that grows lies about its value.
          transform={`rotate(-90 ${C} ${C})`}
          className={arc}
        />
      )}
    </>
  );
}

/** "$125,000" large and ".00" small: the exact figure without the cents crowding the ring. */
function Hero({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="hatch tabular text-xl font-extrabold text-unknown sm:text-2xl">{UNKNOWN}</span>;
  }
  const [whole, cents] = formatMoneyCell(value).split(".");
  return (
    <span className="tabular whitespace-nowrap text-xl font-extrabold leading-none tracking-[-0.02em] sm:text-2xl">
      {whole}
      {cents !== undefined && <span className="text-sm font-bold text-muted sm:text-base">.{cents}</span>}
    </span>
  );
}

function Swatch({ ring }: { ring: "outer" | "inner" }) {
  // The swatch is the ring in miniature: thick ink for the outside ring, thin grey for the inside one.
  return (
    <span
      aria-hidden="true"
      className={clsx(
        "row-span-2 mt-1 inline-block h-3 w-3 rounded-full border-solid",
        ring === "outer" ? "border-[5px] border-content" : "border-[3px] border-muted",
      )}
    />
  );
}

function LegendRow({
  ring,
  pct,
  title,
  sum,
}: {
  ring: "outer" | "inner";
  pct: number | null;
  title: string;
  sum: string | null;
}) {
  const label = pctLabel(pct);
  return (
    <div className="grid grid-cols-[0.75rem_1fr] gap-x-3">
      <Swatch ring={ring} />
      <dt className="text-sm font-semibold">{title}</dt>
      <dd className="col-start-2 mt-0.5">
        <span
          className={clsx(
            "tabular block text-[1.625rem] font-extrabold leading-none tracking-[-0.02em]",
            label === null && "hatch w-fit text-unknown",
          )}
        >
          {label ?? UNKNOWN}
        </span>
        <span className="tabular mt-1.5 block text-[0.8125rem] text-muted">{sum ?? "We do not have the figures for this."}</span>
      </dd>
    </div>
  );
}

/**
 * The Account card's hero: net liquidation at the centre of a two-ring donut. The outer ring is
 * the share of buying power used (cash secured against short puts, over buying power); the inner
 * ring is the share of the account sitting in cash. Each ring's percent and the sum behind it are
 * written beside it, so nothing is read off an arc alone. A ring we cannot draw is an empty track
 * and an n/a, never a zero.
 */
export function AccountDonut({
  netLiq,
  netLiqStale,
  usedPct,
  cashPct,
  usedSum,
  cashSum,
}: {
  netLiq: number | null;
  netLiqStale: boolean;
  usedPct: number | null;
  cashPct: number | null;
  /** "$18,000 of $80,000 buying power", or null when a part is unknown. */
  usedSum: string | null;
  cashSum: string | null;
}) {
  const used = pctLabel(usedPct);
  const cash = pctLabel(cashPct);
  const summary = `Net liquidation ${netLiq === null ? "unknown" : formatMoneyCell(netLiq)}. Buying power used ${used ?? "unknown"}. Cash ${cash ?? "unknown"} of the account.`;
  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center sm:justify-center sm:gap-14">
      <div className="relative size-48 shrink-0 sm:size-56" data-testid="account-donut">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={summary} className="size-full">
          <Ring {...OUTER} fraction={ringFraction(usedPct)} arc="stroke-content" />
          <Ring {...INNER} fraction={ringFraction(cashPct)} arc="stroke-muted" />
        </svg>
        <div className="absolute inset-0 grid place-content-center justify-items-center gap-1.5 text-center">
          <span className="text-[0.8125rem] text-muted">Net liquidation{netLiqStale ? " · stale" : ""}</span>
          <Hero value={netLiq} />
        </div>
      </div>
      <dl className="grid w-full max-w-sm gap-6 sm:w-auto sm:max-w-md">
        <LegendRow ring="outer" pct={usedPct} title="Buying power used" sum={usedSum} />
        <LegendRow ring="inner" pct={cashPct} title="Cash left" sum={cashSum} />
      </dl>
    </div>
  );
}
