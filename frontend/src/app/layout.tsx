import type { Metadata, Viewport } from "next";
import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusBar";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ChatWidget } from "@/components/chat/ChatWidget";
import { ServiceWorkerRegistration } from "@/components/pwa/ServiceWorkerRegistration";
import { InstallPrompt } from "@/components/pwa/InstallPrompt";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bloomvalley Terminal",
  description: "Personal Bloomberg-style Investment Terminal",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Bloomvalley",
  },
};

export const viewport: Viewport = {
  themeColor: "#8B5CF6",
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <head>
        <link rel="apple-touch-icon" href="/icon-192.svg" />
      </head>
      <body className="h-full overflow-hidden bg-terminal-bg-primary text-terminal-text-primary">
        <Providers>
          <ServiceWorkerRegistration />
          <InstallPrompt />
          <div className="flex h-full">
            <Sidebar />
            <div className="flex flex-col flex-1 min-w-0">
              <main className="flex-1 overflow-y-auto p-3 pt-14 md:p-6 md:pt-6 pwa-safe-top">{children}</main>
              <StatusBar />
            </div>
          </div>
          <CommandPalette />
          <ChatWidget />
        </Providers>
      </body>
    </html>
  );
}
