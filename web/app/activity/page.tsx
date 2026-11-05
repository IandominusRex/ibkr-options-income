import type { Metadata } from "next";
import { Suspense } from "react";
import { ActivityPage } from "@/features/activity/ActivityPage";

export const metadata: Metadata = { title: "Activity" };

// useSearchParams (the view and the Pay month) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <ActivityPage />
    </Suspense>
  );
}
