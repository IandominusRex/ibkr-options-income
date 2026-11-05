import type { Metadata } from "next";

// The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
export async function generateMetadata({ params }: { params: Promise<{ approvalId: string }> }): Promise<Metadata> {
  const { approvalId } = await params;
  return { title: `Proposal ${decodeURIComponent(approvalId)}` };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
