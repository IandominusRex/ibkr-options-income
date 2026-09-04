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
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted">{label}</span>
      <span className={`tabular text-sm ${value === null ? "text-unknown" : "text-content"}`}>
        {value === null ? UNKNOWN : value.toFixed(2)}
      </span>
    </div>
  );
}

function Badge({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return (
      <span className="rounded px-2 py-0.5 text-xs text-unknown">{label}: {UNKNOWN}</span>
    );
  }
  return (
    <span className="rounded bg-elevated px-2 py-0.5 text-xs text-content">
      {label}: {value}
    </span>
  );
}

export function TechnicalsPanel({ data }: { data: Technicals }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Metric label="RSI 14" value={data.rsi_14} />
        <Metric label="MACD" value={data.macd} />
        <Metric label="Signal" value={data.macd_signal} />
        <Metric label="SMA 50" value={data.sma_50} />
        <Metric label="SMA 200" value={data.sma_200} />
        <Metric label="ATR 14" value={data.atr_14} />
      </div>
      <div className="flex gap-2">
        <Badge label="Phase" value={data.phase} />
        <Badge label="Regime" value={data.regime} />
      </div>
    </div>
  );
}