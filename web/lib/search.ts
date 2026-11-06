/**
 * The console's one search palette is mounted once, in the root layout (web overhaul Part 6). Anything
 * that offers search (the rail, More, Research) opens it through this event instead of mounting a
 * second palette, so ⌘K and every Search button reach the same dialog.
 */
export const OPEN_SEARCH_EVENT = "ibkr:open-search";

export function openSearch(): void {
  window.dispatchEvent(new Event(OPEN_SEARCH_EVENT));
}
