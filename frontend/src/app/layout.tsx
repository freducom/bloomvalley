import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusBar";
import { CommandPalette } from "@/components/layout/CommandPalette";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bloomvalley Terminal",
  description: "Personal Bloomberg-style Investment Terminal",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full overflow-hidden bg-terminal-bg-primary text-terminal-text-primary">
        <Providers>
          <div className="flex h-full">
            <Sidebar />
            <div className="flex flex-col flex-1 min-w-0">
              <main className="flex-1 overflow-y-auto p-3 pt-14 md:p-6 md:pt-6">{children}</main>
              <StatusBar />
            </div>
          </div>
          <CommandPalette />
        </Providers>
      </body>
    </html>
  );
}
