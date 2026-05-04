import type { Metadata } from "next";

export const metadata: Metadata = { title: "Optimization" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
