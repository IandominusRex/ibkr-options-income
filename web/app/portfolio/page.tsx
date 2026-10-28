import { Suspense } from "react";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";

// useSearchParams (the view) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <PortfolioPage />
    </Suspense>
  );
}
