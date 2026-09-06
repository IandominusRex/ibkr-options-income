// Empty state: one line of text plus nothing else. No icon circle above a
// heading (per P1 §8.1's table).
export function EmptyState({ text }: { text: string }) {
  return <p className="text-sm text-muted">{text}</p>;
}