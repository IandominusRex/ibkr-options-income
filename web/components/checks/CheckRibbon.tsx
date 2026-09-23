import clsx from "clsx";

type Props = {
  category: string;
  passed: number;
  failed: number;
  unknown: number;
  total: number;
  notApplicable?: boolean;
};

type SegmentState = "pass" | "fail" | "unknown" | "na";

export function CheckRibbon({
  category,
  passed,
  failed,
  unknown,
  total,
  notApplicable,
}: Props) {
  const segments = buildSegments(passed, failed, unknown, total, notApplicable);
  const evaluable = passed + failed;
  const label = notApplicable
    ? `${category} - not applicable`
    : `${category}: ${passed} passed, ${failed} failed, ${unknown} unknown of ${total} checks`;

  return (
    <div className="flex items-center gap-3" role="img" aria-label={label}>
      <div className="flex gap-1" aria-hidden="true">
        {segments.map((state, i) => (
          <span
            key={i}
            data-testid="segment"
            data-state={state}
            className={clsx("h-2.5 w-6 rounded-sm", segmentClass(state))}
          />
        ))}
      </div>
      <ScoreLine
        passed={passed}
        evaluable={evaluable}
        unknown={unknown}
        total={total}
        notApplicable={notApplicable}
      />
    </div>
  );
}

function buildSegments(
  passed: number,
  failed: number,
  unknown: number,
  total: number,
  notApplicable?: boolean,
): SegmentState[] {
  if (notApplicable) {
    return Array.from({ length: total }, () => "na" as SegmentState);
  }
  const out: SegmentState[] = [];
  for (let i = 0; i < passed; i++) out.push("pass");
  for (let i = 0; i < failed; i++) out.push("fail");
  for (let i = 0; i < unknown; i++) out.push("unknown");
  while (out.length < total) out.push("unknown");
  return out.slice(0, total);
}

function segmentClass(state: SegmentState): string {
  switch (state) {
    case "pass":
      return "bg-gain";
    case "fail":
      return "border border-loss";
    case "unknown":
      return "hatch";
    case "na":
      return "bg-surface opacity-50";
  }
}

function ScoreLine({
  passed,
  evaluable,
  unknown,
  total,
  notApplicable,
}: {
  passed: number;
  evaluable: number;
  unknown: number;
  total: number;
  notApplicable?: boolean;
}) {
  if (notApplicable) {
    return <span className="text-xs text-muted">not applicable</span>;
  }
  return (
    <span className="text-xs text-muted">
      {unknown > 0 ? (
        <>
          <span>
            {passed} of {evaluable}
          </span>
          <span> · {unknown} unknown</span>
        </>
      ) : (
        <span>
          {passed} of {total}
        </span>
      )}
    </span>
  );
}