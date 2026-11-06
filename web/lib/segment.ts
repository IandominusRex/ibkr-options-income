/**
 * A dynamic route segment, decoded for a page title. A malformed escape (a stray "%" in a hand-typed
 * URL) makes `decodeURIComponent` throw, which would fail the title rather than the page; the raw
 * segment is the honest fallback (web overhaul Part 6, from a Part 4 review nit).
 */
export function decodeSegment(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
