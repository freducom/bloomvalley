"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiGetRaw, apiDelete } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Private } from "@/lib/privacy";
import { TickerLink } from "@/components/ui/TickerLink";

interface Transaction {
  id: number;
  accountId: number;
  accountName: string | null;
  accountType: string | null;
  securityId: number | null;
  ticker: string | null;
  securityName: string | null;
  type: string;
  tradeDate: string;
  settlementDate: string | null;
  quantity: string;
  priceCents: number;
  priceCurrency: string;
  totalCents: number;
  feeCents: number;
  feeCurrency: string;
  currency: string;
  notes: string | null;
  createdAt: string;
}

interface TransactionSummary {
  totalTransactions: number;
  byType: Record<string, number>;
  earliestDate: string | null;
  latestDate: string | null;
}

interface PaginatedResponse {
  data: Transaction[];
  pagination: { total: number; limit: number; offset: number; hasMore: boolean };
}

const TYPE_COLORS: Record<string, string> = {
  buy: "bg-green-900/40 text-green-400",
  sell: "bg-red-900/40 text-red-400",
  dividend: "bg-purple-900/40 text-purple-400",
  transfer_in: "bg-blue-900/40 text-blue-400",
  transfer_out: "bg-orange-900/40 text-orange-400",
  fee: "bg-yellow-900/40 text-yellow-400",
  tax: "bg-gray-700/40 text-gray-400",
  interest: "bg-cyan-900/40 text-cyan-400",
  deposit: "bg-emerald-900/40 text-emerald-400",
  withdrawal: "bg-rose-900/40 text-rose-400",
};

const PAGE_SIZE = 50;

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [summary, setSummary] = useState<TransactionSummary | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  // Filters
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [accountFilter, setAccountFilter] = useState<string>("");
  const [search, setSearch] = useState("");

  const fetchTransactions = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      if (typeFilter) params.set("type", typeFilter);
      if (accountFilter) params.set("accountId", accountFilter);

      const res = await apiGetRaw<PaginatedResponse>(`/transactions?${params}`);
      setTransactions(res.data);
      setTotal(res.pagination.total);
    } catch (e) {
      console.error("Failed to load transactions", e);
    } finally {
      setLoading(false);
    }
  }, [offset, typeFilter, accountFilter]);

  useEffect(() => {
    fetchTransactions();
  }, [fetchTransactions]);

  useEffect(() => {
    apiGet<TransactionSummary>("/transactions/summary").then(setSummary).catch(console.error);
  }, []);

  // Reset offset when filters change
  useEffect(() => {
    setOffset(0);
  }, [typeFilter, accountFilter]);

  const filtered = search
    ? transactions.filter(
        (t) =>
          (t.ticker && t.ticker.toLowerCase().includes(search.toLowerCase())) ||
          (t.securityName && t.securityName.toLowerCase().includes(search.toLowerCase())) ||
          (t.accountName && t.accountName.toLowerCase().includes(search.toLowerCase()))
      )
    : transactions;

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this transaction?")) return;
    try {
      await apiDelete(`/transactions/${id}`);
      fetchTransactions();
      apiGet<TransactionSummary>("/transactions/summary").then(setSummary).catch(console.error);
    } catch (e) {
      console.error("Failed to delete transaction", e);
    }
  };

  // Unique types from summary for filter dropdown
  const types = summary ? Object.keys(summary.byType).sort() : [];

  // Collect unique accounts from loaded transactions
  const accounts = Array.from(
    new Map(
      transactions
        .filter((t) => t.accountName)
        .map((t) => [t.accountId, t.accountName!])
    )
  );

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Transactions</h1>

      {/* Summary badges */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3">
            <div className="text-xs text-terminal-text-secondary">Total</div>
            <div className="text-xl font-mono font-bold">{summary.totalTransactions}</div>
          </div>
          {Object.entries(summary.byType)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <div
                key={type}
                className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3"
              >
                <div className="text-xs text-terminal-text-secondary capitalize">{type.replace("_", " ")}</div>
                <div className="text-xl font-mono font-bold">{count}</div>
              </div>
            ))}
          {summary.earliestDate && (
            <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-3 col-span-2">
              <div className="text-xs text-terminal-text-secondary">Date Range</div>
              <div className="text-sm font-mono">
                {summary.earliestDate} → {summary.latestDate}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1.5 text-sm"
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t.replace("_", " ")}
            </option>
          ))}
        </select>

        <select
          value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value)}
          className="bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1.5 text-sm"
        >
          <option value="">All accounts</option>
          {accounts.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Search ticker, name, account..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-terminal-bg-secondary border border-terminal-border rounded px-3 py-1.5 text-sm flex-1 min-w-[200px]"
        />

        <div className="text-sm text-terminal-text-secondary self-center ml-auto">
          {total} transaction{total !== 1 ? "s" : ""}
        </div>
      </div>

      {/* Table */}
      <div className="border border-terminal-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-terminal-bg-tertiary text-terminal-text-secondary text-left">
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium text-right">Qty</th>
                <th className="px-3 py-2 font-medium text-right">Price</th>
                <th className="px-3 py-2 font-medium text-right">Total</th>
                <th className="px-3 py-2 font-medium text-right">Fee</th>
                <th className="px-3 py-2 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border">
              {loading ? (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-terminal-text-secondary">
                    Loading...
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-3 py-8 text-center text-terminal-text-secondary">
                    No transactions found.
                  </td>
                </tr>
              ) : (
                filtered.map((t) => (
                  <tr key={t.id} className="hover:bg-terminal-bg-secondary/50">
                    <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                      {t.tradeDate}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-medium capitalize ${
                          TYPE_COLORS[t.type] || "bg-gray-700/40 text-gray-400"
                        }`}
                      >
                        {t.type.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono font-medium">
                      {t.ticker ? (
                        <TickerLink ticker={t.ticker} />
                      ) : (
                        <span className="text-terminal-text-secondary">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-terminal-text-secondary max-w-[200px] truncate">
                      {t.securityName || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-terminal-text-secondary">
                      {t.accountName || "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {parseFloat(t.quantity) !== 0
                        ? <Private>{parseFloat(t.quantity).toLocaleString(undefined, {
                            minimumFractionDigits: 0,
                            maximumFractionDigits: 4,
                          })}</Private>
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {t.priceCents
                        ? formatCurrency(t.priceCents, t.priceCurrency)
                        : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-medium">
                      {t.totalCents ? (
                        <span
                          className={
                            t.type === "sell" || t.type === "dividend"
                              ? "text-green-400"
                              : t.type === "buy"
                              ? "text-red-400"
                              : ""
                          }
                        >
                          <Private>{formatCurrency(t.totalCents, t.currency)}</Private>
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-terminal-text-secondary">
                      {t.feeCents ? <Private>{formatCurrency(t.feeCents, t.feeCurrency)}</Private> : "—"}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <button
                        onClick={() => handleDelete(t.id)}
                        className="text-terminal-text-secondary hover:text-red-400 transition-colors text-xs"
                        title="Delete transaction"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="px-3 py-1.5 text-sm bg-terminal-bg-secondary border border-terminal-border rounded hover:bg-terminal-bg-tertiary disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ← Previous
          </button>
          <span className="text-sm text-terminal-text-secondary">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="px-3 py-1.5 text-sm bg-terminal-bg-secondary border border-terminal-border rounded hover:bg-terminal-bg-tertiary disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
