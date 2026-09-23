"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { RailSection } from "./RailSection";

type NavSection = {
  key: string;
  label: string;
  available: boolean;
  note: string | null;
};

type NavResponse = { as_of: string; sections: NavSection[] };

export function Rail() {
  const { data } = useQuery({
    queryKey: ["nav"],
    queryFn: () => apiFetch<NavResponse>("/nav"),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <nav className="w-[260px] shrink-0 overflow-y-auto border-r border-border bg-surface px-3 py-4">
      <div className="px-3 pb-6 font-mono text-sm text-muted">Research</div>
      <ul className="space-y-1">
        {(data?.sections ?? []).map((s) => (
          <RailSection
            key={s.key}
            sectionKey={s.key}
            label={s.label}
            available={s.available}
            note={s.note}
          />
        ))}
      </ul>
    </nav>
  );
}