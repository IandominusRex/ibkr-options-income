import type { Metadata } from "next";
import { NewsFeed } from "@/components/news/NewsFeed";

export const metadata: Metadata = { title: "News" };

export default function NewsPage() {
  return <NewsFeed />;
}
