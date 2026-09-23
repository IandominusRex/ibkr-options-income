import type { ReactNode } from "react";
import { Tag } from "./Tag";

type Tone = "info" | "positive" | "caution" | "neutral";

/**
 * One bordered, elevated-on-hover box for a single fact inside a grid - the "cards and
 * boxes" unit every explain panel now builds its structural content from, instead of a
 * run of plain paragraphs. A card is for one scannable idea; a paragraph is still the
 * right tool for connective narrative, so panels mix both rather than forcing everything
 * into a box.
 *
 * `bodyClass` overrides the body's default caption-weight styling (`text-xs text-muted`)
 * for callers whose content is substantive rather than incidental - e.g. options/
 * ReviewPanel reuses this shell for Claude's actual review text, which needs to read at
 * the same weight the original plain-paragraph version did (`text-sm text-content`), not
 * as a footnote.
 */
export function FactCard({
  tag,
  tone = "neutral",
  title,
  bodyClass,
  children,
}: {
  tag: string;
  tone?: Tone;
  title: string;
  bodyClass?: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-md border border-border bg-surface p-4">
      <Tag tone={tone}>{tag}</Tag>
      <div className="mt-1.5 font-mono text-sm text-content">{title}</div>
      <p className={`mt-1.5 leading-relaxed ${bodyClass ?? "text-xs text-muted"}`}>{children}</p>
    </div>
  );
}
