"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
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
  ChevronLeft,
  ChevronRight,
  Search,
  type LucideIcon,
} from "lucide-react";

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: "Portfolio",
    items: [
      { label: "Dashboard", href: "/portfolio", icon: LayoutDashboard },
      { label: "Transactions", href: "/transactions", icon: ArrowLeftRight },
      { label: "Import", href: "/import", icon: Upload },
    ],
  },
  {
    title: "Markets",
    items: [
      { label: "Data Feeds", href: "/market", icon: Radio },
      { label: "Watchlist", href: "/watchlist", icon: Eye },
      { label: "Charts", href: "/charts", icon: CandlestickChart },
      { label: "Heatmap", href: "/heatmap", icon: Grid3X3 },
    ],
  },
  {
    title: "Analysis",
    items: [
      { label: "Risk", href: "/risk", icon: ShieldAlert },
      { label: "Research", href: "/research", icon: BookOpen },
      { label: "Fundamentals", href: "/fundamentals", icon: BarChart3 },
    ],
  },
  {
    title: "Income",
    items: [
      { label: "Tax", href: "/tax", icon: Receipt },
      { label: "Fixed Income", href: "/fixed-income", icon: Landmark },
      { label: "Dividends", href: "/dividends", icon: Coins },
    ],
  },
  {
    title: "Macro",
    items: [
      { label: "Dashboard", href: "/macro", icon: Globe },
      { label: "News", href: "/news", icon: Newspaper },
      { label: "Global Events", href: "/global-events", icon: Activity },
    ],
  },
  {
    title: "Tracking",
    items: [
      { label: "Insider", href: "/insider", icon: UserSearch },
      { label: "Recommendations", href: "/recommendations", icon: ThumbsUp },
      { label: "Alerts", href: "/alerts", icon: Bell },
    ],
  },
];

const STORAGE_KEY = "warren-sidebar-collapsed";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setCollapsed(stored === "true");
      }
    } catch {
      // localStorage unavailable — default to expanded
    }

    const handleResize = () => {
      if (window.innerWidth < 1440) {
        setCollapsed(true);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // ignore
    }
  };

  const isActive = (href: string) => {
    if (href === "/portfolio") {
      return pathname === "/" || pathname === "/portfolio" || pathname.startsWith("/portfolio/");
    }
    return pathname === href || pathname.startsWith(href + "/");
  };

  return (
    <aside
      className={`
        flex flex-col h-full bg-terminal-bg-secondary border-r border-terminal-border
        transition-all duration-300 ease-in-out shrink-0 overflow-hidden
        ${collapsed ? "w-14" : "w-60"}
      `}
    >
      {/* Logo area */}
      <div className="flex items-center h-12 px-3 border-b border-terminal-border shrink-0">
        {!collapsed && (
          <span className="font-mono font-bold text-lg text-terminal-accent whitespace-nowrap">
            WC
          </span>
        )}
        {collapsed && (
          <span className="font-mono font-bold text-lg text-terminal-accent mx-auto">
            W
          </span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-1">
            {!collapsed && (
              <div className="px-3 py-1.5 text-xs font-medium text-terminal-text-tertiary uppercase tracking-wider">
                {group.title}
              </div>
            )}
            {collapsed && <div className="h-px bg-terminal-border mx-2 my-1" />}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={collapsed ? item.label : undefined}
                  className={`
                    flex items-center gap-2.5 mx-1 px-2.5 py-1.5 rounded-sm
                    transition-colors duration-150 relative group
                    ${
                      active
                        ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                        : "text-terminal-text-secondary hover:bg-terminal-bg-hover hover:text-terminal-text-primary"
                    }
                  `}
                >
                  {/* Active indicator bar */}
                  {active && (
                    <div className="absolute left-0 top-1 bottom-1 w-[3px] rounded-r bg-terminal-accent" />
                  )}

                  <Icon
                    size={18}
                    className={`shrink-0 ${collapsed ? "mx-auto" : ""}`}
                  />

                  {!collapsed && (
                    <span className="text-sm font-medium whitespace-nowrap">
                      {item.label}
                    </span>
                  )}

                  {/* Tooltip for collapsed state */}
                  {collapsed && (
                    <div
                      className="
                        absolute left-full ml-2 px-2 py-1 rounded-sm
                        bg-terminal-bg-tertiary text-terminal-text-primary text-xs font-medium
                        shadow-sm whitespace-nowrap
                        opacity-0 invisible group-hover:opacity-100 group-hover:visible
                        transition-opacity duration-150 delay-300
                        pointer-events-none z-50
                      "
                    >
                      {item.label}
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Search button */}
      <button
        onClick={() => {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
        }}
        className="
          flex items-center gap-2.5 h-10 mx-1 px-2.5 rounded-sm
          text-terminal-text-secondary hover:text-terminal-text-primary
          hover:bg-terminal-bg-hover transition-colors duration-150
        "
        aria-label="Search (Cmd+K)"
      >
        <Search size={18} className={collapsed ? "mx-auto" : ""} />
        {!collapsed && (
          <>
            <span className="text-sm flex-1">Search</span>
            <kbd className="text-[10px] text-terminal-text-tertiary bg-terminal-bg-tertiary px-1.5 py-0.5 rounded font-mono">
              {"\u2318"}K
            </kbd>
          </>
        )}
      </button>

      {/* Toggle button */}
      <button
        onClick={toggleCollapsed}
        className="
          flex items-center justify-center h-10 mx-1 mb-2 rounded-sm
          text-terminal-text-secondary hover:text-terminal-text-primary
          hover:bg-terminal-bg-hover transition-colors duration-150
        "
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        {!collapsed && <span className="text-sm ml-2">Collapse</span>}
      </button>
    </aside>
  );
}
