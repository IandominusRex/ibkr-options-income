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
      <body className="bg-background text-content font-sans antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Rail />
            <main className="flex-1 overflow-x-hidden">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}