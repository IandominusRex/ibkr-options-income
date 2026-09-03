import Link from "next/link";
import clsx from "clsx";

const HREF: Record<string, string> = {
  research: "/",
  options: "/options",
  portfolio: "/portfolio",
  pnl: "/pnl",
  universe: "/universe",
};

export function RailSection({
  sectionKey,
  label,
  available,
  note,
}: {
  sectionKey: string;
  label: string;
  available: boolean;
  note: string | null;
}) {
  const base = "block rounded-md px-3 py-2 text-sm transition-colors";

  if (!available) {
    return (
      // aria-disabled on a listitem is deliberate: the rail shows the finished shape of
      // the product with unavailable sections greyed out, not hidden. The jsx-a11y rule
      // prefers role=button for aria-disabled, but a disabled link is not a button.
      // eslint-disable-next-line jsx-a11y/role-supports-aria-props
      <li aria-disabled="true" className={clsx(base, "text-muted cursor-default")}>
        <span className="flex items-center justify-between gap-2">
          <span>{label}</span>
          {note && <span className="text-[11px] text-unknown">{note}</span>}
        </span>
      </li>
    );
  }

  return (
    <li>
      <Link
        href={HREF[sectionKey] ?? "/"}
        className={clsx(base, "text-content hover:bg-surface focus-visible:bg-surface")}
      >
        {label}
      </Link>
    </li>
  );
}