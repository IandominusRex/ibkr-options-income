import { StageBadge } from "./StageBadge";
import { UNKNOWN } from "@/lib/format";
import type { AlternativeStrike } from "./types";

export function AlternativesTable({ alternatives }: { alternatives: AlternativeStrike[] }) {
  if (alternatives.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-muted">
        Other contracts assessed on this run
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-2 font-medium">Strike</th>
            <th className="py-2 font-medium">Stage</th>
            <th className="py-2 font-medium">Score</th>
            <th className="py-2 font-medium">Premium</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {alternatives.map((a) => (
            <tr key={a.candidate_id}>
              <td className="py-2 tabular font-mono text-content">
                {a.strike.toFixed(2)}
              </td>
              <td className="py-2">
                {a.stage && <StageBadge stage={a.stage as never} />}
              </td>
              <td className="py-2 tabular">
                {a.blended_score != null ? a.blended_score.toFixed(1) : UNKNOWN}
              </td>
              <td className="py-2 tabular">
                {a.premium != null ? `$${a.premium.toFixed(2)}` : UNKNOWN}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}