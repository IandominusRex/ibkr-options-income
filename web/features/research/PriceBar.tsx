import { price } from "@/components/value/format";
import { layoutBar } from "./format";
import type { BarPoint, TopItem } from "./types";

const TRACK_H = 28;
const LANE_H = 38;
const LANE_H_WRAPPED = 52;

/** "Fair value, half sale": the second name follows in lower case. */
function labelName(names: string[]): string {
  return names.map((n, i) => (i === 0 ? n : n.charAt(0).toLowerCase() + n.slice(1))).join(", ");
}

/** The marker's shape differs by level, so the label is not the only thing telling them apart. */
function Marker({ kind }: { kind: BarPoint["kind"] }) {
  switch (kind) {
    case "price":
      return <span className="block size-3 rounded-full bg-content ring-2 ring-surface" />;
    case "ceiling":
      return <span className="block h-[18px] w-0 border-l-2 border-dashed border-content" />;
    case "stop":
      return <span className="block h-[14px] w-[3px] rounded-sm bg-muted" />;
    default:
      return <span className="block h-[18px] w-[3px] rounded-sm bg-content" />;
  }
}

const ALIGN: Record<BarPoint["align"], string> = {
  start: "text-left",
  center: "-translate-x-1/2 text-center",
  end: "-translate-x-full text-right",
};

/**
 * One bar: the price, the entry ceiling, fair value (the half sale sits there too), and the stop
 * when the API supplies one. Static: nothing grows in. A level with no number is not drawn; the
 * card says so beneath, hatched.
 */
export function PriceBar({ item }: { item: TopItem }) {
  const layout = layoutBar(item);
  if (layout.points.length === 0) return null;
  const laneH = layout.points.some((p) => p.names.length > 1) ? LANE_H_WRAPPED : LANE_H;
  const known = (k: BarPoint["kind"]) => layout.points.find((p) => p.kind === k);
  const priceAt = known("price");
  const fairAt = known("fair");
  const room =
    priceAt && fairAt && priceAt.pct < fairAt.pct ? { left: priceAt.pct, width: fairAt.pct - priceAt.pct } : null;
  const aria = layout.points.map((p) => p.names.map((n) => `${n} ${price(p.value)}`).join(", ")).join("; ");

  return (
    <div role="img" aria-label={aria} className="mt-3">
      <div className="relative" style={{ height: TRACK_H }}>
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-sunk" />
        {room && (
          <div
            className="absolute top-1/2 h-1.5 -translate-y-1/2 bg-border"
            style={{ left: `${room.left}%`, width: `${room.width}%` }}
          />
        )}
        {layout.points.map((p) => (
          <div
            key={p.kind}
            className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
            style={{ left: `${p.pct}%` }}
            aria-hidden="true"
          >
            <Marker kind={p.kind} />
          </div>
        ))}
      </div>
      <div className="relative" style={{ height: layout.lanes * laneH }}>
        {/* Leaders first, labels after, so a label always sits over a line that passes behind it. */}
        {layout.points
          .filter((p) => p.lane > 0)
          .map((p) => (
            <span
              key={`leader-${p.kind}`}
              aria-hidden="true"
              className="absolute w-px bg-border"
              style={{ left: `${p.pct}%`, top: 0, height: p.lane * laneH }}
            />
          ))}
        {layout.points.map((p) => (
          <div
            key={p.kind}
            className={`absolute w-[5.5rem] bg-surface ${ALIGN[p.align]}`}
            style={{ left: `${p.pct}%`, top: p.lane * laneH }}
          >
            <div className="text-xs leading-tight text-muted">{labelName(p.names)}</div>
            <div className="tabular text-[0.8125rem] font-semibold">{price(p.value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
