import { Suspense } from "react";
import { ActivityPage } from "@/features/activity/ActivityPage";

// useSearchParams (the view and the Pay month) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <ActivityPage />
    </Suspense>
  );
}
