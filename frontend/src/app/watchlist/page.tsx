"use client";

import { useEffect, useState, useCallback } from "react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import Link from "next/link";

interface WatchlistSummary {
  id: number;
  name: string;
  description: string | null;
  isDefault: boolean;
  itemCount: number;
  createdAt: string;
}

interface WatchlistItem {
  id: number;
  securityId: number;
  ticker: string;
  name: string;
  assetClass: string;
  currency: string;
  exchange: string | null;
  sector: string | null;
  notes: string | null;
  priceCents: number | null;
  priceDate: string | null;
  dayChangeCents: number | null;
  dayChangePct: number | null;
  addedAt: string;
}

interface WatchlistDetail {
  id: number;
  name: string;
  description: string | null;
  isDefault: boolean;
  items: WatchlistItem[];
}

interface SecurityOption {
  id: number;
  ticker: string;
  name: string;
  assetClass: string;
}

export default function WatchlistPage() {
  const [watchlists, setWatchlists] = useState<WatchlistSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [detail, setDetail] = useState<WatchlistDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  // Add security modal
  const [showAdd, setShowAdd] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [securities, setSecurities] = useState<SecurityOption[]>([]);

  const loadWatchlists = useCallback(async () => {
    try {
      const data = await apiGet<WatchlistSummary[]>("/watchlists/");
      setWatchlists(data);
      if (data.length > 0 && activeId === null) {
        setActiveId(data[0].id);
      }
    } catch (e) {
      console.error("Failed to load watchlists:", e);
    }
  }, [activeId]);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const data = await apiGet<WatchlistDetail>(`/watchlists/${id}`);
      setDetail(data);
    } catch (e) {
      console.error("Failed to load watchlist:", e);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      await loadWatchlists();
      setLoading(false);
    };
    init();
  }, [loadWatchlists]);

  useEffect(() => {
    if (activeId !== null) {
      loadDetail(activeId);
    }
  }, [activeId, loadDetail]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    try {
      await apiPost("/watchlists/", {
        name: newName,
        description: newDesc || null,
      });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      await loadWatchlists();
    } catch (e) {
      console.error("Failed to create watchlist:", e);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await apiDelete(`/watchlists/${id}`);
      if (activeId === id) {
        setActiveId(null);
        setDetail(null);
      }
      await loadWatchlists();
    } catch (e) {
      console.error("Failed to delete watchlist:", e);
    }
  };

  const handleAddSecurity = async (securityId: number) => {
    if (!activeId) return;
    try {
      await apiPost(`/watchlists/${activeId}/items`, {
        security_id: securityId,
      });
      setShowAdd(false);
      setSearchTerm("");
      await loadDetail(activeId);
      await loadWatchlists();
    } catch (e) {
      console.error("Failed to add security:", e);
    }
  };

  const handleRemoveSecurity = async (securityId: number) => {
    if (!activeId) return;
    try {
      await apiDelete(`/watchlists/${activeId}/items/${securityId}`);
      await loadDetail(activeId);
      await loadWatchlists();
    } catch (e) {
      console.error("Failed to remove security:", e);
    }
  };

  const loadSecurities = useCallback(async () => {
    try {
      const data = await apiGet<SecurityOption[]>(
        `/securities?limit=200&search=${encodeURIComponent(searchTerm)}`
      );
      setSecurities(data);
    } catch {
      // fallback: load all
      try {
        const data = await apiGet<SecurityOption[]>("/securities?limit=200");
        setSecurities(data);
      } catch (e) {
        console.error("Failed to load securities:", e);
      }
    }
  }, [searchTerm]);

  useEffect(() => {
    if (showAdd) {
      loadSecurities();
    }
  }, [showAdd, loadSecurities]);

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-8 bg-terminal-bg-secondary rounded w-48 mb-6" />
        <div className="h-64 bg-terminal-bg-secondary rounded" />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Watchlists</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 text-sm font-mono bg-terminal-accent text-white rounded hover:bg-terminal-accent/80 transition-colors"
        >
          + New Watchlist
        </button>
      </div>

      {/* Create watchlist modal */}
      {showCreate && (
        <div className="mb-6 p-4 bg-terminal-bg-secondary border border-terminal-border rounded-md">
          <h2 className="text-sm font-medium text-terminal-text-secondary mb-3">
            New Watchlist
          </h2>
          <div className="flex flex-col gap-2 max-w-md">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Watchlist name"
              className="bg-terminal-bg-primary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent"
              autoFocus
            />
            <input
              type="text"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="Description (optional)"
              className="bg-terminal-bg-primary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent"
            />
            <div className="flex gap-2 mt-1">
              <button
                onClick={handleCreate}
                disabled={!newName.trim()}
                className="px-3 py-1.5 text-sm font-mono bg-terminal-accent text-white rounded hover:bg-terminal-accent/80 disabled:opacity-50 transition-colors"
              >
                Create
              </button>
              <button
                onClick={() => {
                  setShowCreate(false);
                  setNewName("");
                  setNewDesc("");
                }}
                className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-text-primary transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {watchlists.length === 0 ? (
        <div className="flex items-center justify-center h-64 border border-terminal-border rounded-md bg-terminal-bg-secondary">
          <p className="text-terminal-text-secondary">
            No watchlists yet. Create one to start tracking securities.
          </p>
        </div>
      ) : (
        <div className="flex gap-4">
          {/* Watchlist tabs (sidebar) */}
          <div className="w-48 shrink-0">
            <div className="space-y-1">
              {watchlists.map((wl) => (
                <button
                  key={wl.id}
                  onClick={() => setActiveId(wl.id)}
                  className={`w-full text-left px-3 py-2 rounded text-sm transition-colors group ${
                    activeId === wl.id
                      ? "bg-terminal-bg-tertiary text-terminal-text-primary"
                      : "text-terminal-text-secondary hover:bg-terminal-bg-secondary hover:text-terminal-text-primary"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium truncate">{wl.name}</span>
                    <span className="text-xs text-terminal-text-tertiary ml-1">
                      {wl.itemCount}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Watchlist content */}
          <div className="flex-1 min-w-0">
            {detail ? (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-lg font-semibold">{detail.name}</h2>
                    {detail.description && (
                      <p className="text-sm text-terminal-text-tertiary">
                        {detail.description}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setShowAdd(true)}
                      className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-accent hover:border-terminal-accent transition-colors"
                    >
                      + Add
                    </button>
                    <button
                      onClick={() => handleDelete(detail.id)}
                      className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-negative hover:border-terminal-negative transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {/* Add security modal */}
                {showAdd && (
                  <div className="mb-4 p-4 bg-terminal-bg-secondary border border-terminal-border rounded-md">
                    <input
                      type="text"
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      placeholder="Search securities..."
                      className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent mb-2"
                      autoFocus
                    />
                    <div className="max-h-48 overflow-y-auto space-y-1">
                      {securities
                        .filter(
                          (s) =>
                            !detail.items.some(
                              (i) => i.securityId === s.id
                            ) &&
                            (searchTerm === "" ||
                              s.ticker
                                .toLowerCase()
                                .includes(searchTerm.toLowerCase()) ||
                              s.name
                                .toLowerCase()
                                .includes(searchTerm.toLowerCase()))
                        )
                        .map((s) => (
                          <button
                            key={s.id}
                            onClick={() => handleAddSecurity(s.id)}
                            className="w-full text-left px-3 py-1.5 rounded text-sm hover:bg-terminal-bg-tertiary transition-colors flex items-center gap-3"
                          >
                            <span className="font-mono text-terminal-accent w-20 shrink-0">
                              {s.ticker}
                            </span>
                            <span className="truncate text-terminal-text-primary">
                              {s.name}
                            </span>
                            <span className="text-xs text-terminal-text-tertiary ml-auto shrink-0">
                              {s.assetClass}
                            </span>
                          </button>
                        ))}
                    </div>
                    <button
                      onClick={() => {
                        setShowAdd(false);
                        setSearchTerm("");
                      }}
                      className="mt-2 px-3 py-1 text-xs font-mono text-terminal-text-secondary hover:text-terminal-text-primary transition-colors"
                    >
                      Close
                    </button>
                  </div>
                )}

                {detail.items.length === 0 ? (
                  <div className="flex items-center justify-center h-48 border border-terminal-border rounded-md bg-terminal-bg-secondary">
                    <p className="text-terminal-text-secondary text-sm">
                      Empty watchlist. Add securities to track.
                    </p>
                  </div>
                ) : (
                  <div className="border border-terminal-border rounded-md overflow-hidden">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-sm">
                          <th className="text-left px-4 py-2 font-medium">
                            Ticker
                          </th>
                          <th className="text-left px-4 py-2 font-medium">
                            Name
                          </th>
                          <th className="text-left px-4 py-2 font-medium">
                            Class
                          </th>
                          <th className="text-right px-4 py-2 font-medium">
                            Price
                          </th>
                          <th className="text-right px-4 py-2 font-medium">
                            Day Change
                          </th>
                          <th className="text-right px-4 py-2 font-medium">
                            Day %
                          </th>
                          <th className="text-center px-4 py-2 font-medium">
                            Chart
                          </th>
                          <th className="text-center px-4 py-2 font-medium" />
                        </tr>
                      </thead>
                      <tbody>
                        {detail.items.map((item) => {
                          const changeColor =
                            (item.dayChangeCents ?? 0) > 0
                              ? "text-terminal-positive"
                              : (item.dayChangeCents ?? 0) < 0
                              ? "text-terminal-negative"
                              : "text-terminal-text-tertiary";
                          return (
                            <tr
                              key={item.id}
                              className="border-t border-terminal-border hover:bg-terminal-bg-secondary/50 transition-colors"
                            >
                              <td className="px-4 py-2 font-mono text-terminal-accent text-sm">
                                {item.ticker}
                              </td>
                              <td className="px-4 py-2 text-sm">
                                {item.name}
                              </td>
                              <td className="px-4 py-2">
                                <span
                                  className={`text-xs px-2 py-0.5 rounded font-mono ${
                                    item.assetClass === "stock"
                                      ? "bg-terminal-info/20 text-terminal-info"
                                      : item.assetClass === "etf"
                                      ? "bg-terminal-accent/20 text-terminal-accent"
                                      : item.assetClass === "crypto"
                                      ? "bg-terminal-warning/20 text-terminal-warning"
                                      : "bg-terminal-bg-tertiary text-terminal-text-tertiary"
                                  }`}
                                >
                                  {item.assetClass}
                                </span>
                              </td>
                              <td className="px-4 py-2 text-right font-mono text-sm">
                                {item.priceCents != null
                                  ? formatCurrency(
                                      item.priceCents,
                                      item.currency
                                    )
                                  : "--"}
                              </td>
                              <td
                                className={`px-4 py-2 text-right font-mono text-sm ${changeColor}`}
                              >
                                {item.dayChangeCents != null
                                  ? formatCurrency(
                                      item.dayChangeCents,
                                      item.currency
                                    )
                                  : "--"}
                              </td>
                              <td
                                className={`px-4 py-2 text-right font-mono text-sm ${changeColor}`}
                              >
                                {item.dayChangePct != null
                                  ? formatPercent(item.dayChangePct, true)
                                  : "--"}
                              </td>
                              <td className="px-4 py-2 text-center">
                                <Link
                                  href={`/charts?security=${item.securityId}`}
                                  className="text-xs text-terminal-accent hover:underline font-mono"
                                >
                                  view
                                </Link>
                              </td>
                              <td className="px-4 py-2 text-center">
                                <button
                                  onClick={() =>
                                    handleRemoveSecurity(item.securityId)
                                  }
                                  className="text-xs text-terminal-text-tertiary hover:text-terminal-negative transition-colors font-mono"
                                >
                                  remove
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-48 border border-terminal-border rounded-md bg-terminal-bg-secondary">
                <p className="text-terminal-text-secondary text-sm">
                  Select a watchlist
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
