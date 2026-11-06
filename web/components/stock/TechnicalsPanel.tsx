import { UNKNOWN } from "@/lib/format";

type Technicals = {
  price: number;
  rsi_14: number | null;
  atr_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  sma_20: number | null;
  sma_50: number | null;
  sma_200: number | null;
  phase: string | null;
  regime: string | null;
};

function Metric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className={value === null ? "tabular hatch px-1 text-unknown" : "tabular font-semibold"}>
        {value === null ? UNKNOWN : value.toFixed(2)}
      </dd>
    </div>
  );
}

function Word({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return (
      <span className="hatch inline-block rounded-[6px] px-2 py-px text-xs font-semibold tracking-[0.04em] text-unknown">
        {label}: {UNKNOWN}
      </span>
    );
  }
  return (
    <span className="inline-block rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-muted">
      {label}: {value}
    </span>
  );
}

/** The technicals as figure lines (web overhaul Part 5), two columns from 640px; the phase and the
 * regime as words under them. An unknown figure is a hatched n/a, never 0. */
export function TechnicalsPanel({ data }: { data: Technicals }) {
  return (
    <div>
      <dl className="grid gap-x-6 sm:grid-cols-2">
        <Metric label="RSI 14" value={data.rsi_14} />
        <Metric label="MACD" value={data.macd} />
        <Metric label="Signal" value={data.macd_signal} />
        <Metric label="SMA 50" value={data.sma_50} />
        <Metric label="SMA 200" value={data.sma_200} />
        <Metric label="ATR 14" value={data.atr_14} />
      </dl>
      <p className="mt-3 flex flex-wrap gap-2">
        <Word label="Phase" value={data.phase} />
        <Word label="Regime" value={data.regime} />
      </p>
    </div>
  );
}
