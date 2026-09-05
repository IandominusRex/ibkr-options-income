import { useQuery } from "@tanstack/react-query";
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

export function SectorGrid() {
  const { data } = useQuery({
    queryKey: ["sectors"],
    queryFn: () => apiFetch<SectorsResponse>("/research/sectors"),
  });

  if (!data?.sectors?.length) {
    return <p className="text-sm text-muted">No sector data yet.</p>;
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
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
    </div>
  );
}