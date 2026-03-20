"use client";

import { useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { formatCurrency } from "@/lib/format";

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

type AccountType = "regular" | "osakesaastotili";

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
                        ? parseFloat(row.quantity).toLocaleString("en-US", {
                            maximumFractionDigits: 4,
                          })
                        : "--"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {row.avgPriceCents != null
                        ? formatCurrency(row.avgPriceCents, row.currency || "EUR")
                        : "--"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-sm">
                      {row.marketValueCents != null
                        ? formatCurrency(row.marketValueCents, "EUR")
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
