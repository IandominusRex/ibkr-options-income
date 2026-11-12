import type { Metadata } from "next";
import { ExplainPage } from "@/features/explain/ExplainPage";

export const metadata: Metadata = { title: "How it works" };

export default function Page() {
  return <ExplainPage />;
}
