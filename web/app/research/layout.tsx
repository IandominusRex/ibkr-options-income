import type { Metadata } from "next";

// The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
export const metadata: Metadata = { title: "Research" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
