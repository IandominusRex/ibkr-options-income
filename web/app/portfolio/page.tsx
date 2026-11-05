import type { Metadata } from "next";
import { Suspense } from "react";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";

export const metadata: Metadata = { title: "Portfolio" };

// useSearchParams (the view) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <PortfolioPage />
    </Suspense>
  );
}
