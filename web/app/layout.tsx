import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { Rail } from "@/components/shell/Rail";
import { Providers } from "@/app/providers";

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Research",
  description: "Stock research and options income console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body
        className="bg-background text-content font-sans antialiased"
        suppressHydrationWarning
      >
        <Providers>
          {/* h-screen + overflow-hidden on the row, rather than min-h-screen on a page that
              scrolls as one document, is what lets Rail and main scroll independently below -
              Rail pins in place (its own overflow-y-auto, only relevant once its nav list
              outgrows the viewport) while main scrolls through a page's content. */}
          <div className="flex h-screen overflow-hidden">
            <Rail />
            <main className="flex-1 overflow-y-auto overflow-x-hidden">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}