import type { Metadata } from "next";

// The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
  const { symbol } = await params;
  return { title: `${decodeURIComponent(symbol).toUpperCase()} news` };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
