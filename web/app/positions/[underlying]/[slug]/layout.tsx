import type { Metadata } from "next";
import { decodeSegment } from "@/lib/segment";

// The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
export async function generateMetadata({ params }: { params: Promise<{ underlying: string; slug: string }> }): Promise<Metadata> {
  const { underlying } = await params;
  return { title: `${decodeSegment(underlying).toUpperCase()} position` };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
