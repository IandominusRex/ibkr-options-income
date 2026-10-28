"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * A page's view, kept in `?view=` so a reload or a shared link keeps it. No value, or one that is
 * not one of `views`, is `fallback`. Choosing a view writes it into the URL and keeps every other
 * parameter. A page using this must render inside <Suspense> (Next's useSearchParams rule).
 */
export function useViewParam<T extends string>(views: readonly T[], fallback: T): [T, (v: T) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("view");
  const value = (views as readonly string[]).includes(raw ?? "") ? (raw as T) : fallback;

  const set = useCallback(
    (v: T) => {
      const next = new URLSearchParams(params.toString());
      next.set("view", v);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, router, pathname],
  );

  return [value, set];
}
