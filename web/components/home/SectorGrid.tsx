import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { SectorCard } from "./SectorCard";

type SectorMover = { symbol: string; change_pct: number | null };

type SectorCardData = {
  sector: string;
  count: number;
  change_pct: number | null;
  best: SectorMover;
  worst: SectorMover;
  avg_iv_rank: number | null;
  iv_rank_count: number;
};

type SectorsResponse = {
  as_of: string;
  sectors: SectorCardData[];
};

/**
 * The Sectors card on Research (web overhaul Part 6): one white card, "Sectors by IV rank", a row per
 * sector in the API's order (highest average IV rank first; a sector with no IV history last). Loading
 * holds its place; a failed read and an empty answer are sentences.
 */
export function SectorGrid() {
  const { data, isError } = useQuery({
    queryKey: ["sectors"],
    queryFn: () => apiFetch<SectorsResponse>("/research/sectors"),
  });

  let body;
  if (!data && isError) {
    body = <p className="mt-2 text-sm">The sectors could not be loaded right now.</p>;
  } else if (!data) {
    body = <div role="status" aria-busy="true" aria-label="Loading the sectors" className="mt-3 h-40 rounded-xl bg-sunk" />;
  } else if (!data.sectors?.length) {
    body = <p className="mt-2 text-sm">No sector data yet.</p>;
  } else {
    body = (
      <ul className="mt-1">
        {data.sectors.map((s) => (
          <SectorCard
            key={s.sector}
            sector={s.sector}
            count={s.count}
            changePct={s.change_pct}
            best={s.best}
            worst={s.worst}
            avgIvRank={s.avg_iv_rank}
            ivRankCount={s.iv_rank_count}
          />
        ))}
      </ul>
    );
  }

  return (
    <Card aria-labelledby="sectors-title">
      <h2 id="sectors-title" className="text-[1.0625rem] font-bold">
        Sectors by IV rank
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">The names the scan covers, by sector. A move is today&apos;s price change.</p>
      {body}
    </Card>
  );
}
