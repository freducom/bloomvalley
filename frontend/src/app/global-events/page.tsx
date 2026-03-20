"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGetRaw, apiPut } from "@/lib/api";

interface SecurityLink {
  securityId: number;
  ticker: string | null;
  name: string | null;
  impactDirection: string | null;
  impactSeverity: string | null;
  impactReasoning: string | null;
}

interface NewsItem {
  id: number;
  title: string;
  url: string;
  source: string;
  publishedAt: string;
  summary: string | null;
  isGlobal: boolean;
  isBookmarked: boolean;
  securities: SecurityLink[];
}

const CATEGORIES = [
  { key: "", label: "All" },
  { key: "stock market", label: "Markets" },
  { key: "interest rate", label: "Rates" },
  { key: "inflation", label: "Inflation" },
  { key: "Federal Reserve", label: "Fed" },
  { key: "ECB", label: "ECB" },
  { key: "bond", label: "Bonds" },
  { key: "trade", label: "Trade" },
];

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

export default function GlobalEventsPage() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const loadNews = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("isGlobal", "true");
      if (category) params.set("q", category);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      const res = await apiGetRaw<{
        data: NewsItem[];
        pagination: { total: number };
      }>(`/news?${params}`);
      if (offset === 0) {
        setNews(res.data);
      } else {
        setNews((prev) => [...prev, ...res.data]);
      }
      setTotal(res.pagination.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [category, offset]);

  useEffect(() => {
    setOffset(0);
  }, [category]);

  useEffect(() => {
    loadNews();
  }, [loadNews]);

  const toggleBookmark = async (id: number, current: boolean) => {
    try {
      await apiPut(`/news/${id}/bookmark`, { isBookmarked: !current });
      setNews((prev) =>
        prev.map((n) => (n.id === id ? { ...n, isBookmarked: !current } : n))
      );
    } catch {
      /* ignore */
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Global Events</h1>
        <span className="text-sm text-terminal-text-secondary">
          {total} article{total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Category filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            onClick={() => setCategory(c.key)}
            className={`px-3 py-1.5 text-sm rounded border transition-colors ${
              category === c.key
                ? "border-terminal-accent text-terminal-accent bg-terminal-accent/10"
                : "border-terminal-border text-terminal-text-secondary hover:text-terminal-text-primary hover:border-terminal-text-secondary"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* News list */}
      <div className="space-y-2">
        {loading && news.length === 0 ? (
          <div className="text-terminal-text-secondary text-sm p-8 text-center">
            Loading...
          </div>
        ) : news.length === 0 ? (
          <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
            <p className="text-terminal-text-secondary text-sm">
              No global events found. Run the news pipeline to fetch articles.
            </p>
          </div>
        ) : (
          news.map((item) => (
            <div
              key={item.id}
              className="border border-terminal-border rounded bg-terminal-bg-secondary p-3 hover:border-terminal-text-secondary transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-terminal-text-primary hover:text-terminal-accent leading-snug"
                  >
                    {item.title}
                  </a>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-terminal-text-secondary">
                      {timeAgo(item.publishedAt)}
                    </span>
                    {item.summary && (
                      <span className="text-xs text-terminal-text-secondary truncate max-w-md">
                        {item.summary.replace(/&nbsp;/g, " ").replace(/<[^>]*>/g, "")}
                      </span>
                    )}
                  </div>
                  {item.securities.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {item.securities.map((sec) => (
                        <span
                          key={sec.securityId}
                          className="text-xs font-mono px-1.5 py-0.5 rounded bg-terminal-bg-tertiary text-terminal-accent border border-terminal-border"
                        >
                          {sec.ticker}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => toggleBookmark(item.id, item.isBookmarked)}
                  className={`text-lg flex-shrink-0 ${
                    item.isBookmarked
                      ? "text-terminal-warning"
                      : "text-terminal-text-secondary hover:text-terminal-warning"
                  }`}
                >
                  {item.isBookmarked ? "\u2605" : "\u2606"}
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {news.length < total && (
        <div className="mt-4 text-center">
          <button
            onClick={() => setOffset((prev) => prev + limit)}
            disabled={loading}
            className="px-4 py-2 text-sm border border-terminal-border rounded text-terminal-text-secondary hover:text-terminal-accent hover:border-terminal-accent disabled:opacity-50"
          >
            {loading ? "Loading..." : `Load more (${news.length} of ${total})`}
          </button>
        </div>
      )}
    </div>
  );
}
