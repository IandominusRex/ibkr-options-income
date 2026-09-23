import type { ReactNode } from "react";
import { PipelineMap } from "./PipelineMap";
import { SourceRefs } from "./SourceRefs";
import { TiesInto } from "./TiesInto";
import type { SourceRef, TabKey, TieIn } from "./types";

/**
 * The one layout every subtab (bar Overview, which composes the map differently) shares:
 * the pipeline map with this tab lit up, a title and one-line dek, freeform content, then
 * the ties-into chips and the source-file bridge. Keeping this in one place is what makes
 * "every subtab shows how it connects to the others" true by construction rather than by
 * each panel remembering to add it.
 */
export function PanelShell({
  tab,
  title,
  dek,
  onNavigate,
  children,
  ties,
  files,
}: {
  tab: TabKey;
  title: string;
  dek: string;
  onNavigate: (tab: TabKey) => void;
  children: ReactNode;
  ties: TieIn[];
  files: SourceRef[];
}) {
  return (
    <div>
      <PipelineMap active={tab} onNavigate={onNavigate} />

      <header className="mt-6">
        <h2 className="font-mono text-xl text-content">{title}</h2>
        <p className="mt-1 text-sm text-muted">{dek}</p>
      </header>

      <div className="mt-5 flex flex-col gap-4 text-sm leading-relaxed text-content">
        {children}
      </div>

      <TiesInto items={ties} onNavigate={onNavigate} />
      <SourceRefs files={files} />
    </div>
  );
}
