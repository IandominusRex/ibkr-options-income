import type { Metadata } from "next";
import { NewsPage } from "@/features/news/NewsPage";

export const metadata: Metadata = { title: "News" };

export default function Page() {
  return <NewsPage />;
}
