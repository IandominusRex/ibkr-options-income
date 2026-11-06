import type { LucideIcon } from "lucide-react";
import { ArrowLeftRight, Ellipsis, Home, Newspaper, PieChart, Receipt, Telescope } from "lucide-react";

export type NavItem = {
  key: string;
  label: string;
  href: string;
  /** Path prefixes this destination owns; "/" matches only exactly. */
  match: string[];
  icon: LucideIcon;
  /** On the phone tab bar (the rest live under More). */
  phone: boolean;
};

export const NAV: NavItem[] = [
  { key: "home", label: "Home", href: "/", match: ["/"], icon: Home, phone: true },
  { key: "trades", label: "Trades", href: "/trades", match: ["/trades"], icon: ArrowLeftRight, phone: true },
  { key: "portfolio", label: "Portfolio", href: "/portfolio", match: ["/portfolio"], icon: PieChart, phone: true },
  { key: "activity", label: "Activity", href: "/activity", match: ["/activity", "/ledger"], icon: Receipt, phone: true },
  { key: "research", label: "Research", href: "/research", match: ["/research", "/stock"], icon: Telescope, phone: false },
  { key: "news", label: "News", href: "/news", match: ["/news"], icon: Newspaper, phone: false },
  { key: "more", label: "More", href: "/more", match: ["/more", "/explain"], icon: Ellipsis, phone: true },
];

/**
 * The phone tab bar's current tab: Research and News have no tab of their own on a phone (they
 * are reached through More), so their pages mark More current rather than nothing.
 */
export function phoneActiveKey(pathname: string): string | null {
  const key = activeKey(pathname);
  const item = NAV.find((n) => n.key === key);
  return item && !item.phone ? "more" : key;
}

export function activeKey(pathname: string): string | null {
  let best: { key: string; len: number } | null = null;
  for (const item of NAV) {
    for (const m of item.match) {
      const hit = m === "/" ? pathname === "/" : pathname === m || pathname.startsWith(`${m}/`);
      if (hit && (best === null || m.length > best.len)) best = { key: item.key, len: m.length };
    }
  }
  return best?.key ?? null;
}
