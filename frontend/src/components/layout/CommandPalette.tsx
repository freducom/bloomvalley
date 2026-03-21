"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  LayoutDashboard,
  ArrowLeftRight,
  Upload,
  Radio,
  Eye,
  CandlestickChart,
  ShieldAlert,
  BookOpen,
  BarChart3,
  Grid3X3,
  Receipt,
  Landmark,
  Coins,
  Globe,
  Newspaper,
  UserSearch,
  ThumbsUp,
  Bell,
  Activity,
  Play,
  Plus,
  type LucideIcon,
} from "lucide-react";

// --- Types ---

interface PaletteItem {
  id: string;
  label: string;
  description?: string;
  category: "recent" | "feature" | "security" | "action";
  icon?: LucideIcon;
  href?: string;
  action?: () => void;
  badge?: string;
}

interface SecurityResult {
  id: number;
  ticker: string;
  name: string;
  assetClass: string;
}

// --- Static data ---

const FEATURES: PaletteItem[] = [
  { id: "f-portfolio", label: "Dashboard", description: "Portfolio overview", category: "feature", icon: LayoutDashboard, href: "/portfolio", badge: "Cmd+1" },
  { id: "f-transactions", label: "Transactions", description: "Trade history", category: "feature", icon: ArrowLeftRight, href: "/transactions", badge: "Cmd+2" },
  { id: "f-import", label: "Import", description: "Import from Nordnet", category: "feature", icon: Upload, href: "/import", badge: "Cmd+3" },
  { id: "f-market", label: "Data Feeds", description: "Market data pipelines", category: "feature", icon: Radio, href: "/market" },
  { id: "f-watchlist", label: "Watchlist", description: "Tracked securities", category: "feature", icon: Eye, href: "/watchlist" },
  { id: "f-charts", label: "Charts", description: "Price charts", category: "feature", icon: CandlestickChart, href: "/charts" },
  { id: "f-heatmap", label: "Heatmap", description: "Portfolio heatmap", category: "feature", icon: Grid3X3, href: "/heatmap" },
  { id: "f-risk", label: "Risk", description: "Risk analysis", category: "feature", icon: ShieldAlert, href: "/risk" },
  { id: "f-research", label: "Research", description: "Research notes", category: "feature", icon: BookOpen, href: "/research" },
  { id: "f-fundamentals", label: "Fundamentals", description: "Earnings & financials", category: "feature", icon: BarChart3, href: "/fundamentals" },
  { id: "f-tax", label: "Tax", description: "Finnish tax analysis", category: "feature", icon: Receipt, href: "/tax" },
  { id: "f-fixed-income", label: "Fixed Income", description: "Bonds & dividend income", category: "feature", icon: Landmark, href: "/fixed-income" },
  { id: "f-dividends", label: "Dividends", description: "Dividend calendar & income", category: "feature", icon: Coins, href: "/dividends" },
  { id: "f-macro", label: "Macro Dashboard", description: "Macroeconomic overview", category: "feature", icon: Globe, href: "/macro" },
  { id: "f-news", label: "News", description: "Financial news feed", category: "feature", icon: Newspaper, href: "/news" },
  { id: "f-global-events", label: "Global Events", description: "Global macro news", category: "feature", icon: Activity, href: "/global-events" },
  { id: "f-insider", label: "Insider", description: "Insider trading signals", category: "feature", icon: UserSearch, href: "/insider" },
  { id: "f-recommendations", label: "Recommendations", description: "Buy/sell/hold recs", category: "feature", icon: ThumbsUp, href: "/recommendations" },
  { id: "f-alerts", label: "Alerts", description: "Price & event alerts", category: "feature", icon: Bell, href: "/alerts" },
];

const ACTIONS: PaletteItem[] = [
  { id: "a-add-transaction", label: "Add Transaction", category: "action", icon: Plus, href: "/transactions" },
  { id: "a-import", label: "Import from Nordnet", category: "action", icon: Upload, href: "/import" },
  { id: "a-create-alert", label: "Create Alert", category: "action", icon: Bell, href: "/alerts" },
  { id: "a-run-prices", label: "Run Price Pipeline", category: "action", icon: Play, action: () => runPipeline("yahoo_daily_prices") },
  { id: "a-run-news", label: "Run News Pipeline", category: "action", icon: Play, action: () => runPipeline("google_news") },
  { id: "a-run-macro", label: "Run Macro Pipeline", category: "action", icon: Play, action: () => runPipeline("fred_macro_indicators") },
];

async function runPipeline(name: string) {
  try {
    const base = process.env.NEXT_PUBLIC_API_URL || "";
    await fetch(`${base}/api/v1/pipelines/${name}/run`, { method: "POST" });
  } catch {
    // silently fail — status bar or toast should handle feedback
  }
}

// --- Recent items persistence ---

const RECENT_KEY = "warren-command-palette-recent";
const MAX_RECENT = 5;

function getRecent(): PaletteItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as PaletteItem[];
  } catch {
    return [];
  }
}

function addRecent(item: PaletteItem) {
  try {
    const recent = getRecent().filter((r) => r.id !== item.id);
    const entry: PaletteItem = { id: item.id, label: item.label, description: item.description, category: "recent", href: item.href, badge: item.badge };
    recent.unshift(entry);
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, MAX_RECENT)));
  } catch {
    // localStorage unavailable
  }
}

// --- Component ---

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [securities, setSecurities] = useState<PaletteItem[]>([]);
  const [recentItems, setRecentItems] = useState<PaletteItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();

  // Global Cmd+K listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Focus input and load recents when opening
  useEffect(() => {
    if (open) {
      setQuery("");
      setHighlighted(0);
      setSecurities([]);
      setRecentItems(getRecent());
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  // Debounced security search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (query.length < 1) {
      setSecurities([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL || "";
        const res = await fetch(`${base}/api/v1/securities?q=${encodeURIComponent(query)}&limit=5`);
        if (!res.ok) return;
        const json = await res.json();
        const data: SecurityResult[] = json.data || [];
        setSecurities(
          data.map((s) => ({
            id: `s-${s.id}`,
            label: `${s.ticker} — ${s.name}`,
            category: "security" as const,
            href: `/charts?security=${s.id}`,
            badge: s.assetClass,
          }))
        );
      } catch {
        setSecurities([]);
      }
    }, 200);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // Build flat results list
  const buildResults = useCallback((): { category: string; items: PaletteItem[] }[] => {
    const sections: { category: string; items: PaletteItem[] }[] = [];

    if (!query) {
      // Show recents when no query
      if (recentItems.length > 0) {
        sections.push({ category: "Recent", items: recentItems });
      }
      sections.push({ category: "Features", items: FEATURES.slice(0, 5) });
      sections.push({ category: "Actions", items: ACTIONS.slice(0, 3) });
      return sections;
    }

    const q = query.toLowerCase();

    const matchedFeatures = FEATURES.filter(
      (f) => f.label.toLowerCase().includes(q) || (f.description?.toLowerCase().includes(q))
    ).slice(0, 5);

    const matchedActions = ACTIONS.filter(
      (a) => a.label.toLowerCase().includes(q)
    ).slice(0, 5);

    if (matchedFeatures.length > 0) sections.push({ category: "Features", items: matchedFeatures });
    if (securities.length > 0) sections.push({ category: "Securities", items: securities });
    if (matchedActions.length > 0) sections.push({ category: "Actions", items: matchedActions });

    return sections;
  }, [query, securities, recentItems]);

  const sections = buildResults();
  const flatItems = sections.flatMap((s) => s.items);

  // Reset highlight when results change
  useEffect(() => {
    setHighlighted(0);
  }, [query, securities.length]);

  // Select an item
  const selectItem = (item: PaletteItem) => {
    addRecent(item);
    setOpen(false);
    if (item.action) {
      item.action();
    } else if (item.href) {
      router.push(item.href);
    }
  };

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((prev) => Math.min(prev + 1, flatItems.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (flatItems[highlighted]) {
        selectItem(flatItems[highlighted]);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  // Scroll highlighted item into view
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector(`[data-index="${highlighted}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [highlighted]);

  if (!open) return null;

  let flatIndex = 0;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh]"
      onClick={() => setOpen(false)}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-[rgba(10,14,23,0.7)]" />

      {/* Palette */}
      <div
        className="relative w-[560px] max-h-[480px] bg-terminal-bg-secondary border border-terminal-border rounded-lg shadow-[0_4px_12px_rgba(0,0,0,0.4)] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-terminal-border">
          <Search size={18} className="text-terminal-text-tertiary shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search features, securities, actions..."
            className="flex-1 bg-transparent text-sm text-terminal-text-primary placeholder-terminal-text-tertiary outline-none font-sans"
          />
          <kbd className="text-[10px] text-terminal-text-tertiary bg-terminal-bg-tertiary px-1.5 py-0.5 rounded font-mono">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="overflow-y-auto flex-1">
          {sections.length === 0 && query.length > 0 && (
            <div className="px-4 py-8 text-center text-sm text-terminal-text-tertiary">
              No results found
            </div>
          )}

          {sections.map((section) => (
            <div key={section.category}>
              <div className="px-4 py-1.5 text-[11px] font-medium text-terminal-text-tertiary uppercase tracking-wider">
                {section.category}
              </div>
              {section.items.map((item) => {
                const idx = flatIndex++;
                const Icon = item.icon;
                const isHighlighted = idx === highlighted;

                return (
                  <button
                    key={item.id}
                    data-index={idx}
                    onClick={() => selectItem(item)}
                    onMouseEnter={() => setHighlighted(idx)}
                    className={`
                      w-full flex items-center gap-3 px-4 h-10 text-left text-sm transition-colors duration-75
                      ${isHighlighted
                        ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                        : "text-terminal-text-secondary hover:bg-terminal-bg-hover"
                      }
                    `}
                  >
                    {Icon && <Icon size={16} className="shrink-0 text-terminal-text-tertiary" />}
                    {!Icon && <div className="w-4" />}
                    <span className="flex-1 truncate">{item.label}</span>
                    {item.badge && (
                      <span className="text-[10px] text-terminal-text-tertiary bg-terminal-bg-primary px-1.5 py-0.5 rounded font-mono">
                        {item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
