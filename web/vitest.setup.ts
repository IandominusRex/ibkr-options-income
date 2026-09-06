import "@testing-library/jest-dom/vitest";

// jsdom has no matchMedia. Components query it for prefers-reduced-motion;
// a permissive stub lets tests override via vi.stubGlobal or run with the
// default (no preference).
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: (_: string, __: unknown) => {},
      removeEventListener: (_: string, __: unknown) => {},
      addListener: (_: unknown) => {},
      removeListener: (_: unknown) => {},
      dispatchEvent: (_: unknown) => false,
    }),
  });
}