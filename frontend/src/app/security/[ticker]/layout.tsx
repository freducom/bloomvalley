import type { Metadata } from "next";

export function generateMetadata({
  params,
}: {
  params: { ticker: string };
}): Metadata {
  return { title: decodeURIComponent(params.ticker) };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
