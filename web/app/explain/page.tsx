import type { Metadata } from "next";
import { ExplainShell } from "@/components/explain/ExplainShell";

export const metadata: Metadata = { title: "How it works" };

export default function ExplainPage() {
  return <ExplainShell />;
}
