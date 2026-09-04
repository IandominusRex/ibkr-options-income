export function SectionShell({
  title,
  state,
  reason,
  children,
}: {
  title: string;
  state: "ready" | "pending" | "unavailable";
  reason?: string | null;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">{title}</h2>
      {state === "ready" && children}
      {state === "pending" && (
        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
          {reason ?? "Building this section. It will appear shortly."}
        </p>
      )}
      {state === "unavailable" && (
        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
          {reason ?? "Not available for this symbol."}
        </p>
      )}
    </section>
  );
}