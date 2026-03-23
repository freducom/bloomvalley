"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiGetRaw, apiPost } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Private } from "@/lib/privacy";

interface ImportRow {
  id: number;
  rowNumber: number;
  ticker: string | null;
  isin: string | null;
  name: string | null;
  quantity: string | null;
  avgPriceCents: number | null;
  marketValueCents: number | null;
  currency: string | null;
  accountType: string | null;
  matchStatus: string;
  action: string;
  securityId: number | null;
  errorMessage: string | null;
}

interface ImportDetail {
  id: number;
  source: string;
  status: string;
  accountId: number | null;
  accountName?: string;
  totalRows: number;
  matchedRows: number;
  unmatchedRows: number;
  metadata: Record<string, unknown> | null;
  createdAt: string;
  rows: ImportRow[];
}

interface ConfirmResult {
  importId: number;
  status: string;
  transactionsCreated: number;
  accountId: number;
}

interface SecurityResult {
  id: number;
  ticker: string | null;
  name: string;
  assetClass: string;
}

interface YahooLookup {
  ticker: string;
  name: string;
  assetClass: string;
  currency: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  quoteType: string;
  marketCap: number | null;
  currentPrice: number | null;
}

interface AccountResult {
  id: number;
  name: string;
  type: string;
}

type AccountType = "regular" | "osakesaastotili";

function AddSingleHolding() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SecurityResult[]>([]);
  const [lookupResult, setLookupResult] = useState<YahooLookup | null>(null);
  const [lookingUp, setLookingUp] = useState(false);
  const [selected, setSelected] = useState<SecurityResult | null>(null);
  const [accounts, setAccounts] = useState<AccountResult[]>([]);
  const [accountId, setAccountId] = useState<number | "">("");
  const [showNewAccount, setShowNewAccount] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountType, setNewAccountType] = useState("regular");
  const [creatingAccount, setCreatingAccount] = useState(false);
  const [quantity, setQuantity] = useState("");
  const [avgPrice, setAvgPrice] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [tradeDate, setTradeDate] = useState(() => new Date().toISOString().split("T")[0]);
  const [txType, setTxType] = useState<"transfer_in" | "buy">("transfer_in");
  const [notes, setNotes] = useState("");
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    try {
      const r = await apiGetRaw<{ data: AccountResult[] }>("/accounts");
      setAccounts(r.data);
      if (r.data.length > 0 && accountId === "") setAccountId(r.data[0].id);
    } catch { /* */ }
  }, [accountId]);

  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);

  const searchSecurities = useCallback(async (q: string) => {
    if (q.length < 2) { setResults([]); setLookupResult(null); return; }
    setSearching(true);
    setLookupResult(null);
    try {
      // Search local DB first
      const res = await apiGetRaw<{ data: SecurityResult[] }>(`/securities?q=${encodeURIComponent(q)}&limit=10`);
      setResults(res.data);
    } catch { setResults([]); }
    finally { setSearching(false); }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => searchSecurities(query), 300);
    return () => clearTimeout(timer);
  }, [query, searchSecurities]);

  const handleLookup = async () => {
    if (!query.trim()) return;
    setLookingUp(true);
    setError(null);
    try {
      const res = await apiGet<YahooLookup>(`/securities/lookup/${encodeURIComponent(query.trim())}`);
      setLookupResult(res);
    } catch {
      setError(`Ticker "${query.trim()}" not found on Yahoo Finance`);
      setLookupResult(null);
    } finally {
      setLookingUp(false);
    }
  };

  const handleSelectLookup = async (lk: YahooLookup) => {
    // Create security in DB, then select it
    setSaving(true);
    try {
      const res = await apiPost<{ data: SecurityResult }>("/securities", {
        ticker: lk.ticker,
        name: lk.name,
        asset_class: lk.assetClass,
        currency: lk.currency,
        exchange: lk.exchange,
        sector: lk.sector,
        industry: lk.industry,
        country: lk.country,
      });
      const sec = (res as unknown as { data: SecurityResult }).data;
      setSelected(sec);
      setCurrency(lk.currency);
      if (lk.currentPrice) setAvgPrice(String(lk.currentPrice));
      setQuery("");
      setResults([]);
      setLookupResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add security");
    } finally {
      setSaving(false);
    }
  };

  const handleSelect = (sec: SecurityResult) => {
    setSelected(sec);
    setQuery("");
    setResults([]);
    setLookupResult(null);
  };

  const handleCreateAccount = async () => {
    if (!newAccountName.trim()) return;
    setCreatingAccount(true);
    try {
      const res = await apiPost<{ data: AccountResult }>("/accounts", {
        name: newAccountName.trim(),
        type: newAccountType,
        currency: "EUR",
      });
      const acct = (res as unknown as { data: AccountResult }).data;
      await fetchAccounts();
      setAccountId(acct.id);
      setShowNewAccount(false);
      setNewAccountName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create account");
    } finally {
      setCreatingAccount(false);
    }
  };

  const handleSubmit = async () => {
    if (!selected || !accountId || !quantity) return;
    setSaving(true);
    setError(null);
    setSuccess(null);

    const qty = parseFloat(quantity);
    const price = parseFloat(avgPrice) || 0;
    const priceCents = Math.round(price * 100);
    const totalCents = Math.round(qty * price * 100);

    try {
      await apiPost("/transactions", {
        account_id: accountId,
        security_id: selected.id,
        type: txType,
        trade_date: tradeDate,
        quantity: String(qty),
        price_cents: priceCents || null,
        price_currency: currency,
        total_cents: totalCents,
        fee_cents: 0,
        currency,
        notes: notes || null,
      });
      setSuccess(`Added ${qty} × ${selected.ticker || selected.name}`);
      setSelected(null);
      setQuantity("");
      setAvgPrice("");
      setNotes("");
      setTimeout(() => setSuccess(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add holding");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-6 p-4 bg-terminal-bg-secondary border border-terminal-border rounded-md">
      <h2 className="text-sm font-medium text-terminal-text-secondary mb-3">
        Add Single Holding
      </h2>

      {success && (
        <div className="mb-3 px-3 py-2 bg-terminal-positive/10 border border-terminal-positive/30 rounded text-sm text-terminal-positive">
          {success}
        </div>
      )}
      {error && (
        <div className="mb-3 px-3 py-2 bg-terminal-negative/10 border border-terminal-negative/30 rounded text-sm text-terminal-negative">
          {error}
        </div>
      )}

      {/* Security search */}
      <div className="mb-3 relative">
        {selected ? (
          <div className="flex items-center gap-2 bg-terminal-bg-primary border border-terminal-accent/50 rounded px-3 py-1.5">
            <span className="text-sm font-mono font-medium text-terminal-accent">{selected.ticker}</span>
            <span className="text-sm text-terminal-text-secondary">{selected.name}</span>
            <span className="text-xs text-terminal-text-tertiary ml-auto">{selected.assetClass}</span>
            <button onClick={() => setSelected(null)} className="text-terminal-text-tertiary hover:text-terminal-negative text-xs ml-2">✕</button>
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleLookup(); }}
                placeholder="Search by name, or enter ticker and press Look Up..."
                className="flex-1 bg-terminal-bg-primary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent"
              />
              <button
                onClick={handleLookup}
                disabled={lookingUp || !query.trim()}
                className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-text-primary hover:border-terminal-accent transition-colors disabled:opacity-40"
              >
                {lookingUp ? "Looking up..." : "Look Up"}
              </button>
            </div>
            {searching && <div className="absolute right-28 top-2 text-xs text-terminal-text-tertiary">searching...</div>}

            {/* Local DB results */}
            {(results.length > 0 || lookupResult) && (
              <div className="absolute z-10 w-full mt-1 bg-terminal-bg-primary border border-terminal-border rounded shadow-md max-h-64 overflow-y-auto">
                {results.length > 0 && (
                  <>
                    <div className="px-3 py-1 text-xs text-terminal-text-tertiary bg-terminal-bg-tertiary font-mono">YOUR SECURITIES</div>
                    {results.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => handleSelect(s)}
                        className="w-full text-left px-3 py-2 hover:bg-terminal-bg-tertiary flex items-center gap-2 text-sm"
                      >
                        <span className="font-mono font-medium text-terminal-accent w-24 shrink-0">{s.ticker || "—"}</span>
                        <span className="text-terminal-text-primary truncate">{s.name}</span>
                        <span className="text-xs text-terminal-text-tertiary ml-auto shrink-0">{s.assetClass}</span>
                      </button>
                    ))}
                  </>
                )}
                {lookupResult && (
                  <>
                    <div className="px-3 py-1 text-xs text-terminal-text-tertiary bg-terminal-bg-tertiary font-mono border-t border-terminal-border">YAHOO FINANCE</div>
                    <button
                      onClick={() => handleSelectLookup(lookupResult)}
                      className="w-full text-left px-3 py-2 hover:bg-terminal-bg-tertiary text-sm"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-terminal-warning w-24 shrink-0">{lookupResult.ticker}</span>
                        <span className="text-terminal-text-primary truncate">{lookupResult.name}</span>
                        <span className="text-xs text-terminal-text-tertiary ml-auto shrink-0">{lookupResult.assetClass}</span>
                      </div>
                      <div className="flex gap-3 mt-1 text-xs text-terminal-text-tertiary">
                        {lookupResult.exchange && <span>{lookupResult.exchange}</span>}
                        {lookupResult.currency && <span>{lookupResult.currency}</span>}
                        {lookupResult.sector && <span>{lookupResult.sector}</span>}
                        {lookupResult.country && <span>{lookupResult.country}</span>}
                        {lookupResult.currentPrice != null && <span className="text-terminal-text-secondary font-mono">{lookupResult.currentPrice} {lookupResult.currency}</span>}
                      </div>
                    </button>
                  </>
                )}
                {results.length === 0 && !lookupResult && !searching && query.length >= 2 && (
                  <div className="px-3 py-2 text-xs text-terminal-text-tertiary">
                    No local matches. Click &quot;Look Up&quot; to search Yahoo Finance.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Fields row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 mb-3">
        <div>
          <label className="text-xs text-terminal-text-tertiary">Account</label>
          {showNewAccount ? (
            <div className="flex flex-col gap-1">
              <input
                type="text"
                value={newAccountName}
                onChange={(e) => setNewAccountName(e.target.value)}
                placeholder="Account name"
                className="w-full bg-terminal-bg-primary border border-terminal-accent/50 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-terminal-accent"
                autoFocus
              />
              <select
                value={newAccountType}
                onChange={(e) => setNewAccountType(e.target.value)}
                className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1 text-xs"
              >
                <option value="regular">Regular (AOT)</option>
                <option value="osakesaastotili">OST</option>
                <option value="pension">Pension</option>
                <option value="crypto">Crypto</option>
              </select>
              <div className="flex gap-1">
                <button
                  onClick={handleCreateAccount}
                  disabled={creatingAccount || !newAccountName.trim()}
                  className="flex-1 px-2 py-1 text-xs font-mono bg-terminal-accent/20 text-terminal-accent rounded hover:bg-terminal-accent/30 disabled:opacity-40"
                >
                  {creatingAccount ? "..." : "Create"}
                </button>
                <button
                  onClick={() => setShowNewAccount(false)}
                  className="px-2 py-1 text-xs text-terminal-text-tertiary hover:text-terminal-text-primary"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div>
              <select
                value={accountId}
                onChange={(e) => {
                  if (e.target.value === "__new__") { setShowNewAccount(true); return; }
                  setAccountId(Number(e.target.value));
                }}
                className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 text-sm"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
                <option value="__new__">+ New account...</option>
              </select>
            </div>
          )}
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Type</label>
          <select
            value={txType}
            onChange={(e) => setTxType(e.target.value as "transfer_in" | "buy")}
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 text-sm"
          >
            <option value="transfer_in">Transfer In</option>
            <option value="buy">Buy</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Quantity</label>
          <input
            type="text"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="100"
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 font-mono text-sm focus:outline-none focus:border-terminal-accent"
          />
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Avg Price</label>
          <input
            type="text"
            value={avgPrice}
            onChange={(e) => setAvgPrice(e.target.value)}
            placeholder="25.50"
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 font-mono text-sm focus:outline-none focus:border-terminal-accent"
          />
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Currency</label>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 text-sm"
          >
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
            <option value="SEK">SEK</option>
            <option value="GBP">GBP</option>
            <option value="DKK">DKK</option>
            <option value="NOK">NOK</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Trade Date</label>
          <input
            type="date"
            value={tradeDate}
            onChange={(e) => setTradeDate(e.target.value)}
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-terminal-accent"
          />
        </div>
        <div>
          <label className="text-xs text-terminal-text-tertiary">Notes</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
            className="w-full bg-terminal-bg-primary border border-terminal-border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-terminal-accent"
          />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={saving || !selected || !quantity || !accountId}
          className="px-4 py-1.5 bg-terminal-accent text-white rounded font-mono text-sm hover:bg-terminal-accent/80 disabled:opacity-50 transition-colors"
        >
          {saving ? "Adding..." : "Add Holding"}
        </button>
      </div>
    </div>
  );
}

export default function ImportPage() {
  const [text, setText] = useState("");
  const [accountType, setAccountType] = useState<AccountType>("regular");
  const [parsing, setParsing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [importData, setImportData] = useState<ImportDetail | null>(null);
  const [confirmResult, setConfirmResult] = useState<ConfirmResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cashText, setCashText] = useState("");
  const [cashSaved, setCashSaved] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Read as ArrayBuffer to handle UTF-16
    const buffer = await file.arrayBuffer();

    // Try UTF-16 LE first (Nordnet default), then UTF-8
    let decoded: string;
    const bytes = new Uint8Array(buffer);
    if (bytes[0] === 0xff && bytes[1] === 0xfe) {
      // UTF-16 LE BOM
      decoded = new TextDecoder("utf-16le").decode(buffer);
    } else if (bytes[0] === 0xfe && bytes[1] === 0xff) {
      // UTF-16 BE BOM
      decoded = new TextDecoder("utf-16be").decode(buffer);
    } else {
      decoded = new TextDecoder("utf-8").decode(buffer);
    }

    setText(decoded);

    // Auto-detect account type from filename
    const name = file.name.toLowerCase();
    if (name.includes("ost") || name.includes("osakesääst")) {
      setAccountType("osakesaastotili");
    } else {
      setAccountType("regular");
    }
  };

  const handleParse = async () => {
    if (!text.trim()) return;
    setParsing(true);
    setError(null);
    setImportData(null);
    setConfirmResult(null);

    try {
      const result = await apiPost<{ data: { id: number } }>("/imports/parse", {
        text,
        account_type: accountType,
        account_name: accountType === "osakesaastotili" ? "Nordnet OST" : "Nordnet AOT",
      });
      const importId = (result as unknown as { data: { id: number } }).data.id;
      const detail = await apiGet<ImportDetail>(`/imports/${importId}`);
      setImportData(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Parse failed");
    } finally {
      setParsing(false);
    }
  };

  const handleConfirm = async () => {
    if (!importData) return;
    setConfirming(true);
    setError(null);

    try {
      const result = await apiPost<{ data: ConfirmResult }>(
        `/imports/${importData.id}/confirm`
      );
      setConfirmResult((result as unknown as { data: ConfirmResult }).data);
      setImportData(null);
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm failed");
    } finally {
      setConfirming(false);
    }
  };

  const handleCancel = async () => {
    if (!importData) return;
    try {
      await apiPost(`/imports/${importData.id}/cancel`);
      setImportData(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cancel failed");
    }
  };

  const handleSaveCash = async () => {
    if (!cashText.trim()) return;
    setCashSaved(false);
    try {
      await apiPost("/accounts/cash", { text: cashText });
      setCashSaved(true);
      setTimeout(() => setCashSaved(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save cash balance");
    }
  };

  const actionBadge = (action: string) => {
    const styles: Record<string, string> = {
      transfer_in: "bg-terminal-positive/20 text-terminal-positive",
      buy: "bg-terminal-info/20 text-terminal-info",
      sell: "bg-terminal-negative/20 text-terminal-negative",
      skip: "bg-terminal-bg-tertiary text-terminal-text-tertiary",
    };
    return (
      <span
        className={`text-xs px-2 py-0.5 rounded font-mono ${
          styles[action] || styles.skip
        }`}
      >
        {action.replace("_", " ")}
      </span>
    );
  };

  const matchBadge = (status: string) => {
    const styles: Record<string, string> = {
      auto_matched: "bg-terminal-positive/20 text-terminal-positive",
      ticker_matched: "bg-terminal-info/20 text-terminal-info",
      manual_mapped: "bg-terminal-accent/20 text-terminal-accent",
      unrecognized: "bg-terminal-negative/20 text-terminal-negative",
      skipped: "bg-terminal-bg-tertiary text-terminal-text-tertiary",
    };
    return (
      <span
        className={`text-xs px-2 py-0.5 rounded font-mono ${
          styles[status] || styles.unrecognized
        }`}
      >
        {status.replace("_", " ")}
      </span>
    );
  };

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Nordnet Import</h1>

      {/* Cash Balance Section */}
      <div className="mb-6 p-4 bg-terminal-bg-secondary border border-terminal-border rounded-md">
        <h2 className="text-sm font-medium text-terminal-text-secondary mb-2">
          Cash Balance
        </h2>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={cashText}
            onChange={(e) => setCashText(e.target.value)}
            placeholder="18 871,96 EUR"
            className="flex-1 max-w-xs bg-terminal-bg-primary border border-terminal-border rounded px-3 py-1.5 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary focus:outline-none focus:border-terminal-accent"
          />
          <button
            onClick={handleSaveCash}
            className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-text-primary hover:border-terminal-accent transition-colors"
          >
            Save
          </button>
          {cashSaved && (
            <span className="text-xs text-terminal-positive font-mono">
              Saved
            </span>
          )}
        </div>
      </div>

      {/* Add Single Holding */}
      <AddSingleHolding />

      {/* Success banner */}
      {confirmResult && (
        <div className="mb-6 p-4 bg-terminal-positive/10 border border-terminal-positive/30 rounded-md">
          <p className="text-terminal-positive font-medium">
            Import confirmed: {confirmResult.transactionsCreated} transaction
            {confirmResult.transactionsCreated !== 1 ? "s" : ""} created
          </p>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="mb-6 p-4 bg-terminal-negative/10 border border-terminal-negative/30 rounded-md">
          <p className="text-terminal-negative">{error}</p>
        </div>
      )}

      {!importData ? (
        /* Step 1: Upload or paste */
        <div>
          <div className="flex items-center gap-4 mb-3">
            <label className="text-sm text-terminal-text-secondary">
              Account type:
            </label>
            <div className="flex gap-1">
              {(
                [
                  ["regular", "AOT"],
                  ["osakesaastotili", "OST"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setAccountType(value)}
                  className={`px-3 py-1 text-sm font-mono rounded ${
                    accountType === value
                      ? "bg-terminal-accent/20 text-terminal-accent"
                      : "text-terminal-text-secondary hover:text-terminal-text-primary"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="ml-auto">
              <label className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-text-primary hover:border-terminal-accent transition-colors cursor-pointer">
                Upload CSV
                <input
                  type="file"
                  accept=".csv,.tsv,.txt"
                  onChange={handleFileUpload}
                  className="hidden"
                />
              </label>
            </div>
          </div>

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste your Nordnet portfolio export here, or upload a CSV file..."
            className="w-full h-48 bg-terminal-bg-secondary border border-terminal-border rounded-md p-3 font-mono text-sm text-terminal-text-primary placeholder-terminal-text-tertiary resize-y focus:outline-none focus:border-terminal-accent"
          />
          <div className="mt-3 flex justify-end">
            <button
              onClick={handleParse}
              disabled={parsing || !text.trim()}
              className="px-4 py-2 bg-terminal-accent text-white rounded font-mono text-sm hover:bg-terminal-accent/80 disabled:opacity-50 transition-colors"
            >
              {parsing ? "Parsing..." : "Parse Export"}
            </button>
          </div>
        </div>
      ) : (
        /* Step 2: Review parsed data */
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <span className="text-sm text-terminal-text-secondary">
                {importData.totalRows} rows parsed
              </span>
              <span className="text-sm text-terminal-positive">
                {importData.matchedRows} matched
              </span>
              {importData.unmatchedRows > 0 && (
                <span className="text-sm text-terminal-warning">
                  {importData.unmatchedRows} unmatched
                </span>
              )}
              {importData.metadata && (
                <>
                  {(importData.metadata.closed_positions as number) > 0 && (
                    <span className="text-sm text-terminal-negative">
                      {importData.metadata.closed_positions as number} closed
                    </span>
                  )}
                </>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCancel}
                className="px-3 py-1.5 text-sm font-mono border border-terminal-border text-terminal-text-secondary rounded hover:text-terminal-text-primary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={confirming || importData.matchedRows === 0}
                className="px-4 py-1.5 bg-terminal-positive text-white rounded font-mono text-sm hover:bg-terminal-positive/80 disabled:opacity-50 transition-colors"
              >
                {confirming ? "Importing..." : "Confirm Import"}
              </button>
            </div>
          </div>

          <div className="border border-terminal-border rounded-md overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-terminal-bg-secondary text-terminal-text-secondary text-sm">
                  <th className="text-left px-4 py-2 font-medium">Name</th>
                  <th className="text-right px-4 py-2 font-medium">Qty</th>
                  <th className="text-right px-4 py-2 font-medium">Avg Cost</th>
                  <th className="text-right px-4 py-2 font-medium">Value</th>
                  <th className="text-left px-4 py-2 font-medium">Match</th>
                  <th className="text-left px-4 py-2 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {importData.rows.map((row) => (
                  <tr
                    key={row.id}
                    className={`border-t border-terminal-border transition-colors ${
                      row.matchStatus === "unrecognized"
                        ? "bg-terminal-negative/5"
                        : row.action === "skip"
                        ? "opacity-50"
                        : "hover:bg-terminal-bg-secondary/50"
                    }`}
                  >
                    <td className="px-4 py-2 text-sm">
                      <div className="font-medium">{row.name || row.ticker || "--"}</div>
                      {row.ticker && (
                        <div className="text-xs text-terminal-text-tertiary font-mono">
                          {row.ticker}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {row.quantity
                        ? <Private>{parseFloat(row.quantity).toLocaleString("en-US", {
                            maximumFractionDigits: 4,
                          })}</Private>
                        : "--"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {row.avgPriceCents != null
                        ? <Private>{formatCurrency(row.avgPriceCents, row.currency || "EUR")}</Private>
                        : "--"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {row.marketValueCents != null
                        ? <Private>{formatCurrency(row.marketValueCents, "EUR")}</Private>
                        : "--"}
                    </td>
                    <td className="px-4 py-2">{matchBadge(row.matchStatus)}</td>
                    <td className="px-4 py-2">{actionBadge(row.action)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
