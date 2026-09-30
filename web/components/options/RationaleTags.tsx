// The frozen candidate's rationale tags, rendered as words rather than snake_case codes.
// `iv_rank_unavailable` is the one that matters most: the name has no IV history, so its
// IV component was scored neutral (`missing_iv_rank_score` in scoring_weights.yaml) rather
// than zero. The score is therefore partly a placeholder, and that is an unknown state -
// so it carries the hatch texture as well as the unknown colour, never colour alone.

const LABELS: Record<string, { text: string; unknown: boolean }> = {
  iv_rank_unavailable: {
    text: "IV rank unavailable - IV part of the score is a neutral placeholder",
    unknown: true,
  },
};

export function rationaleTagLabel(tag: string): string {
  return LABELS[tag]?.text ?? tag.replace(/_/g, " ");
}

export function RationaleTags({ tags }: { tags: string[] | undefined }) {
  if (!tags || tags.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2 text-xs">
      {tags.map((tag) => {
        const unknown = LABELS[tag]?.unknown ?? false;
        return (
          <li
            key={tag}
            className={
              unknown
                ? "hatch rounded border border-border px-2 py-0.5 text-unknown"
                : "rounded border border-border px-2 py-0.5 text-muted"
            }
          >
            {rationaleTagLabel(tag)}
          </li>
        );
      })}
    </ul>
  );
}
