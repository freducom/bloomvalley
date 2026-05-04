import type { Metadata } from "next";

export const metadata: Metadata = { title: "ESG" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
