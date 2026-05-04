import type { Metadata } from "next";

export const metadata: Metadata = { title: "Fixed Income" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
