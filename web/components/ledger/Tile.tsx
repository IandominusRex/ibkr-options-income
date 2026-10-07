export function Tile({ id, label, value, tone }: { id: string; label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface p-4" data-testid={`tile-${id}`}>
      <div className="text-xs text-muted">{label}</div>
      <div className={`tabular pt-1 text-lg ${tone ?? "text-content"}`}>{value}</div>
    </div>
  );
}
