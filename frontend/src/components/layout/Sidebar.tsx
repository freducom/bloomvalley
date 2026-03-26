"use client";

import { useState, useEffect, useCallback } from "react";
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
  Briefcase,
  Receipt,
  Landmark,
  Coins,
  Globe,
  Newspaper,
  UserSearch,
  ThumbsUp,
  Bell,
  Activity,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Search,
  Monitor,
  EyeOff,
  Menu,
  X,
  ScanSearch,
  Users,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { usePrivacy } from "@/lib/privacy";

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
      { label: "Recommendations", href: "/recommendations", icon: ThumbsUp },
      { label: "Holdings", href: "/holdings", icon: Briefcase },
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
      { label: "Coverage", href: "/coverage", icon: ScanSearch },
      { label: "Consensus", href: "/consensus", icon: Users },
      { label: "Accuracy", href: "/accuracy", icon: Target },
      { label: "Fundamentals", href: "/fundamentals", icon: BarChart3 },
      { label: "Earnings", href: "/earnings", icon: CalendarClock },
      { label: "Projections", href: "/projections", icon: TrendingUp },
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
      { label: "Alerts", href: "/alerts", icon: Bell },
    ],
  },
];

const STORAGE_KEY = "warren-sidebar-collapsed";

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const { privacyMode, togglePrivacy } = usePrivacy();

  useEffect(() => {
    const checkMobile = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (mobile) {
        setMobileOpen(false);
      } else {
        try {
          const stored = localStorage.getItem(STORAGE_KEY);
          if (stored !== null) {
            setCollapsed(stored === "true");
          }
        } catch { /* */ }
        if (window.innerWidth < 1440) {
          setCollapsed(true);
        }
      }
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Close mobile menu on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Prevent body scroll when mobile menu is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  const toggleCollapsed = useCallback(() => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch { /* */ }
  }, [collapsed]);

  const isActive = (href: string) => {
    if (href === "/portfolio") {
      return pathname === "/" || pathname === "/portfolio" || pathname.startsWith("/portfolio/");
    }
    return pathname === href || pathname.startsWith(href + "/");
  };

  const navContent = (mobile: boolean) => (
    <>
      <nav className={`flex-1 overflow-y-auto py-2 ${mobile ? "px-2" : ""}`}>
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-1">
            {(mobile || !collapsed) && (
              <div className={`px-3 py-1.5 text-xs font-medium text-terminal-text-tertiary uppercase tracking-wider ${mobile ? "text-sm" : ""}`}>
                {group.title}
              </div>
            )}
            {!mobile && collapsed && <div className="h-px bg-terminal-border mx-2 my-1" />}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={!mobile && collapsed ? item.label : undefined}
                  className={`
                    flex items-center gap-2.5 mx-1 px-2.5 rounded-sm
                    transition-colors duration-150 relative group
                    ${mobile ? "py-2.5" : "py-1.5"}
                    ${
                      active
                        ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                        : "text-terminal-text-secondary hover:bg-terminal-bg-hover hover:text-terminal-text-primary"
                    }
                  `}
                >
                  {active && (
                    <div className="absolute left-0 top-1 bottom-1 w-[3px] rounded-r bg-terminal-accent" />
                  )}

                  <Icon
                    size={mobile ? 20 : 18}
                    className={`shrink-0 ${!mobile && collapsed ? "mx-auto" : ""}`}
                  />

                  {(mobile || !collapsed) && (
                    <span className={`font-medium whitespace-nowrap ${mobile ? "text-base" : "text-sm"}`}>
                      {item.label}
                    </span>
                  )}

                  {!mobile && collapsed && (
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

      {/* Footer actions */}
      {mobile ? (
        <div className="border-t border-terminal-border mx-1 pt-2 pb-4 flex justify-center gap-6">
          <button
            onClick={togglePrivacy}
            className={`p-2.5 rounded-sm transition-colors ${
              privacyMode
                ? "text-terminal-warning"
                : "text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
            aria-label={privacyMode ? "Privacy On" : "Privacy Off"}
          >
            {privacyMode ? <EyeOff size={22} /> : <Eye size={22} />}
          </button>
          <button
            onClick={() => {
              document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
            }}
            className="p-2.5 rounded-sm text-terminal-text-secondary hover:text-terminal-text-primary transition-colors"
            aria-label="Search"
          >
            <Search size={22} />
          </button>
        </div>
      ) : (
        <div className="border-t border-terminal-border mx-1 pt-1">
          <Link
            href="/fullscreen"
            className="
              flex items-center gap-2.5 h-9 px-2.5 rounded-sm
              text-terminal-text-secondary hover:text-terminal-text-primary
              hover:bg-terminal-bg-hover transition-colors duration-150
            "
            title={collapsed ? "TV Dashboard" : undefined}
          >
            <Monitor size={18} className={collapsed ? "mx-auto" : ""} />
            {!collapsed && (
              <>
                <span className="text-sm flex-1">TV Dashboard</span>
                <kbd className="text-[10px] text-terminal-text-tertiary bg-terminal-bg-tertiary px-1.5 py-0.5 rounded font-mono">
                  {"\u2318\u21E7"}F
                </kbd>
              </>
            )}
          </Link>

          <button
            onClick={togglePrivacy}
            className={`
              flex items-center gap-2.5 h-9 w-full px-2.5 rounded-sm
              transition-colors duration-150
              ${privacyMode
                ? "text-terminal-warning hover:text-terminal-warning hover:bg-terminal-bg-hover"
                : "text-terminal-text-secondary hover:text-terminal-text-primary hover:bg-terminal-bg-hover"
              }
            `}
            title={collapsed ? `Privacy ${privacyMode ? "On" : "Off"}` : undefined}
          >
            {privacyMode
              ? <EyeOff size={18} className={collapsed ? "mx-auto" : ""} />
              : <Eye size={18} className={collapsed ? "mx-auto" : ""} />
            }
            {!collapsed && (
              <>
                <span className="text-sm flex-1">{privacyMode ? "Privacy On" : "Privacy Off"}</span>
                <kbd className="text-[10px] text-terminal-text-tertiary bg-terminal-bg-tertiary px-1.5 py-0.5 rounded font-mono">
                  {"\u2318\u21E7"}P
                </kbd>
              </>
            )}
          </button>

          <button
            onClick={() => {
              document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
            }}
            className="
              flex items-center gap-2.5 h-9 w-full px-2.5 rounded-sm
              text-terminal-text-secondary hover:text-terminal-text-primary
              hover:bg-terminal-bg-hover transition-colors duration-150
            "
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
        </div>
      )}
    </>
  );

  // Mobile: hamburger button + fullscreen overlay
  if (isMobile) {
    return (
      <>
        {/* Hamburger button — fixed top-left, offset for PWA safe area */}
        <button
          onClick={() => setMobileOpen(true)}
          className="fixed z-40 p-2 rounded bg-terminal-bg-secondary border border-terminal-border text-terminal-text-primary"
          style={{
            top: "calc(0.75rem + env(safe-area-inset-top, 0px))",
            left: "calc(0.75rem + env(safe-area-inset-left, 0px))",
          }}
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>

        {/* Fullscreen overlay menu */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-50 bg-terminal-bg-primary flex flex-col"
            style={{
              paddingTop: "env(safe-area-inset-top, 0px)",
              paddingLeft: "env(safe-area-inset-left, 0px)",
              paddingRight: "env(safe-area-inset-right, 0px)",
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between h-14 px-4 border-b border-terminal-border shrink-0">
              <span className="font-mono font-bold text-lg text-terminal-accent">
                Bloomvalley
              </span>
              <button
                onClick={() => setMobileOpen(false)}
                className="p-2 rounded text-terminal-text-secondary hover:text-terminal-text-primary"
                aria-label="Close menu"
              >
                <X size={22} />
              </button>
            </div>

            {navContent(true)}
          </div>
        )}
      </>
    );
  }

  // Desktop: standard sidebar
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
            Bloomvalley
          </span>
        )}
        {collapsed && (
          <span className="font-mono font-bold text-lg text-terminal-accent mx-auto">
            BV
          </span>
        )}
      </div>

      {navContent(false)}

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
