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
  imageUrl: string | null;
  isGlobal: boolean;
  isBookmarked: boolean;
  securities: SecurityLink[];
  createdAt: string;
}

interface SentimentEntry {
  securityId: number;
  ticker: string | null;
  name: string | null;
  positive: number;
  negative: number;
  neutral: number;
  totalArticles: number;
  sentiment: string;
}

type Tab = "feed" | "bookmarked" | "sentiment";

const IMPACT_COLORS: Record<string, string> = {
  positive: "text-terminal-positive",
  negative: "text-terminal-negative",
  neutral: "text-terminal-text-secondary",
};

const IMPACT_ICONS: Record<string, string> = {
  positive: "\u2191",
  negative: "\u2193",
  neutral: "\u2014",
};

const SEVERITY_BADGES: Record<string, string> = {
  high: "bg-red-900/30 text-red-400 border-red-800",
  medium: "bg-yellow-900/30 text-yellow-400 border-yellow-800",
  low: "bg-gray-800 text-terminal-text-secondary border-terminal-border",
};

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "text-terminal-positive",
  negative: "text-terminal-negative",
  neutral: "text-terminal-text-secondary",
};

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

export default function NewsPage() {
  const [tab, setTab] = useState<Tab>("feed");
  const [news, setNews] = useState<NewsItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterGlobal, setFilterGlobal] = useState<string>("");
  const [sentiment, setSentiment] = useState<SentimentEntry[]>([]);
  const limit = 50;

  const loadNews = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (tab === "bookmarked") params.set("isBookmarked", "true");
      if (searchQuery) params.set("q", searchQuery);
      if (filterGlobal === "global") params.set("isGlobal", "true");
      if (filterGlobal === "securities") params.set("isGlobal", "false");
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      const qs = params.toString();
      const res = await apiGetRaw<{
        data: NewsItem[];
        pagination: { total: number };
      }>(`/news${qs ? `?${qs}` : ""}`);
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
  }, [tab, searchQuery, filterGlobal, offset]);

  const loadSentiment = async () => {
    try {
      const res = await apiGetRaw<{ data: SentimentEntry[] }>(
        "/news/sentiment-summary"
      );
      setSentiment(res.data);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    setOffset(0);
  }, [tab, searchQuery, filterGlobal]);

  useEffect(() => {
    if (tab === "sentiment") {
      loadSentiment();
    } else {
      loadNews();
    }
  }, [tab, loadNews]);

  const toggleBookmark = async (id: number, current: boolean) => {
    try {
      await apiPut(`/news/${id}/bookmark`, { isBookmarked: !current });
      setNews((prev) =>
        prev.map((n) =>
          n.id === id ? { ...n, isBookmarked: !current } : n
        )
      );
    } catch {
      /* ignore */
    }
  };

  const loadMore = () => {
    if (news.length < total) {
      setOffset((prev) => prev + limit);
    }
  };

  const tabs: { key: Tab; label: string }[] = [
    { key: "feed", label: "News Feed" },
    { key: "bookmarked", label: "Bookmarked" },
    { key: "sentiment", label: "Sentiment" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">News</h1>
        <span className="text-sm text-terminal-text-secondary">
          {tab !== "sentiment" && `${total} article${total !== 1 ? "s" : ""}`}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-terminal-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? "border-terminal-accent text-terminal-accent"
                : "border-transparent text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "sentiment" ? (
        <SentimentView data={sentiment} />
      ) : (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-3 mb-4">
            <input
              type="text"
              placeholder="Search news..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary w-60"
            />
            <select
              value={filterGlobal}
              onChange={(e) => setFilterGlobal(e.target.value)}
              className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
            >
              <option value="">All news</option>
              <option value="global">Global / Macro</option>
              <option value="securities">Security-specific</option>
            </select>
          </div>

          {/* News list */}
          <div className="space-y-3">
            {loading && news.length === 0 ? (
              <div className="text-terminal-text-secondary text-sm p-8 text-center">
                Loading...
              </div>
            ) : news.length === 0 ? (
              <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
                <p className="text-terminal-text-secondary text-sm">
                  No news articles found.
                  {tab === "bookmarked" && " Bookmark articles from the feed to see them here."}
                </p>
                <p className="text-terminal-text-secondary text-xs mt-2">
                  Run the Google News pipeline to fetch articles:
                </p>
                <code className="text-xs text-terminal-accent mt-1 block">
                  POST /api/v1/pipelines/google_news/run
                </code>
              </div>
            ) : (
              news.map((item) => (
                <NewsCard
                  key={item.id}
                  item={item}
                  onToggleBookmark={toggleBookmark}
                />
              ))
            )}
          </div>

          {/* Load more */}
          {news.length < total && (
            <div className="mt-4 text-center">
              <button
                onClick={loadMore}
                disabled={loading}
                className="px-4 py-2 text-sm border border-terminal-border rounded text-terminal-text-secondary hover:text-terminal-accent hover:border-terminal-accent disabled:opacity-50"
              >
                {loading ? "Loading..." : `Load more (${news.length} of ${total})`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── News Card ── */

function NewsCard({
  item,
  onToggleBookmark,
}: {
  item: NewsItem;
  onToggleBookmark: (id: number, current: boolean) => void;
}) {
  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-4 hover:border-terminal-text-secondary transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          {/* Title */}
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-terminal-text-primary hover:text-terminal-accent block leading-snug"
          >
            {item.title}
          </a>

          {/* Meta */}
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-xs px-1.5 py-0.5 rounded bg-terminal-bg-tertiary text-terminal-text-secondary">
              {item.source === "google_news"
                ? "Google News"
                : item.source === "manual"
                  ? "Manual"
                  : item.source}
            </span>
            <span className="text-xs text-terminal-text-secondary">
              {timeAgo(item.publishedAt)}
            </span>
            {item.isGlobal && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-terminal-info/10 text-terminal-info border border-terminal-info/30">
                Global
              </span>
            )}
          </div>

          {/* Summary */}
          {item.summary && (
            <p className="text-xs text-terminal-text-secondary mt-2 line-clamp-2 leading-relaxed">
              {item.summary}
            </p>
          )}

          {/* Linked securities */}
          {item.securities.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {item.securities.map((sec) => (
                <span
                  key={sec.securityId}
                  className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-terminal-bg-tertiary border border-terminal-border"
                >
                  <span className="font-mono text-terminal-accent">
                    {sec.ticker}
                  </span>
                  {sec.impactDirection && (
                    <span
                      className={`font-bold ${
                        IMPACT_COLORS[sec.impactDirection] || ""
                      }`}
                    >
                      {IMPACT_ICONS[sec.impactDirection] || ""}
                    </span>
                  )}
                  {sec.impactSeverity && (
                    <span
                      className={`text-[10px] px-1 rounded border ${
                        SEVERITY_BADGES[sec.impactSeverity] || ""
                      }`}
                    >
                      {sec.impactSeverity}
                    </span>
                  )}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Bookmark */}
        <button
          onClick={() => onToggleBookmark(item.id, item.isBookmarked)}
          className={`text-lg flex-shrink-0 transition-colors ${
            item.isBookmarked
              ? "text-terminal-warning"
              : "text-terminal-text-secondary hover:text-terminal-warning"
          }`}
          title={item.isBookmarked ? "Remove bookmark" : "Bookmark"}
        >
          {item.isBookmarked ? "\u2605" : "\u2606"}
        </button>
      </div>
    </div>
  );
}

/* ── Sentiment View ── */

function SentimentView({ data }: { data: SentimentEntry[] }) {
  if (data.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">
          No sentiment data available. Tag news articles with impact direction to see sentiment here.
        </p>
      </div>
    );
  }

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
            <th className="text-left p-3">Security</th>
            <th className="text-center p-3">Sentiment</th>
            <th className="text-center p-3">Positive</th>
            <th className="text-center p-3">Negative</th>
            <th className="text-center p-3">Neutral</th>
            <th className="text-center p-3">Total</th>
          </tr>
        </thead>
        <tbody>
          {data.map((entry) => (
            <tr
              key={entry.securityId}
              className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary"
            >
              <td className="p-3">
                <span className="font-mono text-terminal-accent mr-2">
                  {entry.ticker}
                </span>
                <span className="text-terminal-text-secondary text-xs">
                  {entry.name}
                </span>
              </td>
              <td className="text-center p-3">
                <span
                  className={`inline-flex items-center gap-1 text-xs font-medium ${
                    SENTIMENT_COLORS[entry.sentiment] || ""
                  }`}
                >
                  <span
                    className={`w-2 h-2 rounded-full ${
                      entry.sentiment === "positive"
                        ? "bg-terminal-positive"
                        : entry.sentiment === "negative"
                          ? "bg-terminal-negative"
                          : "bg-terminal-text-secondary"
                    }`}
                  />
                  {entry.sentiment.charAt(0).toUpperCase() +
                    entry.sentiment.slice(1)}
                </span>
              </td>
              <td className="text-center p-3 font-mono text-terminal-positive">
                {entry.positive || "-"}
              </td>
              <td className="text-center p-3 font-mono text-terminal-negative">
                {entry.negative || "-"}
              </td>
              <td className="text-center p-3 font-mono text-terminal-text-secondary">
                {entry.neutral || "-"}
              </td>
              <td className="text-center p-3 font-mono text-terminal-text-primary">
                {entry.totalArticles}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
