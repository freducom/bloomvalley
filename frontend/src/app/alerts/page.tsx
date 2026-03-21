"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGetRaw, apiPost, apiPut, apiDelete } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/format";

/* ── Types ── */

interface AlertRule {
  id: number;
  type: string;
  status: string;
  securityId: number | null;
  ticker: string | null;
  securityName: string | null;
  accountId: number | null;
  thresholdValue: number | null;
  thresholdCurrency: string | null;
  message: string;
  triggeredAt: string | null;
  dismissedAt: string | null;
  expiresAt: string | null;
  createdAt: string;
}

interface AlertHistoryItem {
  id: number;
  alertId: number;
  triggeredValue: number | null;
  triggeredValueCurrency: string | null;
  snapshotData: Record<string, unknown> | null;
  message: string;
  triggeredAt: string;
}

interface SecurityOption {
  id: number;
  ticker: string;
  name: string;
}

type Tab = "rules" | "triggered" | "history";

const TYPE_LABELS: Record<string, string> = {
  price_above: "Price Above",
  price_below: "Price Below",
  drift_threshold: "Drift",
  staleness: "Stale Data",
  dividend_announced: "Dividend",
  insider_activity: "Insider Activity",
  risk_breach: "Risk Breach",
  recommendation_expiry: "Rec. Expiry",
  custom: "Custom",
};

const TYPE_COLORS: Record<string, string> = {
  price_above: "text-terminal-positive bg-terminal-positive/10",
  price_below: "text-terminal-negative bg-terminal-negative/10",
  insider_activity: "text-terminal-accent bg-terminal-accent/10",
  risk_breach: "text-terminal-warning bg-terminal-warning/10",
  recommendation_expiry: "text-terminal-info bg-terminal-info/10",
  dividend_announced: "text-terminal-info bg-terminal-info/10",
  drift_threshold: "text-terminal-warning bg-terminal-warning/10",
  staleness: "text-terminal-text-secondary bg-terminal-bg-tertiary",
  custom: "text-terminal-text-secondary bg-terminal-bg-tertiary",
};

const STATUS_COLORS: Record<string, string> = {
  active: "text-terminal-positive",
  triggered: "text-terminal-warning",
  dismissed: "text-terminal-text-secondary",
  expired: "text-terminal-text-secondary",
};

export default function AlertsPage() {
  const [tab, setTab] = useState<Tab>("rules");
  const [counts, setCounts] = useState({ active: 0, triggered: 0, total: 0 });

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: { active: number; triggered: number; total: number } }>("/alerts/active-count");
        setCounts(res.data);
      } catch { /* */ }
    })();
  }, [tab]);

  const tabs: { key: Tab; label: string; badge?: number }[] = [
    { key: "rules", label: "Alert Rules", badge: counts.active },
    { key: "triggered", label: "Triggered", badge: counts.triggered },
    { key: "history", label: "History" },
  ];

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Alerts</h1>

      <div className="flex gap-1 mb-4 border-b border-terminal-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
              tab === t.key
                ? "border-terminal-accent text-terminal-accent"
                : "border-transparent text-terminal-text-secondary hover:text-terminal-text-primary"
            }`}
          >
            {t.label}
            {t.badge !== undefined && t.badge > 0 && (
              <span className="px-1.5 py-0.5 text-xs rounded-full bg-terminal-accent/20 text-terminal-accent font-mono">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "rules" && <RulesTab />}
      {tab === "triggered" && <TriggeredTab />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}

/* ── Rules Tab ── */

function RulesTab() {
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGetRaw<{ data: AlertRule[]; pagination: { total: number } }>(
        "/alerts?limit=200"
      );
      setAlerts(res.data);
      setTotal(res.pagination.total);
    } catch { /* */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDelete = async (id: number) => {
    try {
      await apiDelete(`/alerts/${id}`);
      load();
    } catch { /* */ }
  };

  const handleReactivate = async (id: number) => {
    try {
      await apiPost(`/alerts/${id}/reactivate`);
      load();
    } catch { /* */ }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <span className="text-sm text-terminal-text-secondary">{total} alert rule{total !== 1 ? "s" : ""}</span>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-1.5 bg-terminal-accent text-terminal-bg-primary text-sm rounded font-medium hover:opacity-90"
        >
          {showCreate ? "Cancel" : "+ New Alert"}
        </button>
      </div>

      {showCreate && (
        <CreateAlertForm
          onCreated={() => { setShowCreate(false); load(); }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {loading ? (
        <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>
      ) : alerts.length === 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">
            No alert rules configured. Create one to start monitoring.
          </p>
        </div>
      ) : (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
                <th className="text-left p-3">Type</th>
                <th className="text-left p-3">Security</th>
                <th className="text-left p-3">Message</th>
                <th className="text-right p-3">Threshold</th>
                <th className="text-center p-3">Status</th>
                <th className="text-left p-3">Created</th>
                <th className="text-right p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                  <td className="p-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${TYPE_COLORS[a.type] || ""}`}>
                      {TYPE_LABELS[a.type] || a.type}
                    </span>
                  </td>
                  <td className="p-3">
                    {a.ticker ? (
                      <span className="font-mono text-terminal-accent">{a.ticker}</span>
                    ) : (
                      <span className="text-xs text-terminal-text-secondary">Portfolio-wide</span>
                    )}
                  </td>
                  <td className="p-3 text-xs max-w-xs truncate">{a.message}</td>
                  <td className="text-right p-3 font-mono text-xs">
                    {a.thresholdValue
                      ? formatCurrency(a.thresholdValue, a.thresholdCurrency || "EUR")
                      : "-"}
                  </td>
                  <td className="text-center p-3">
                    <span className={`text-xs capitalize ${STATUS_COLORS[a.status] || ""}`}>
                      {a.status}
                    </span>
                  </td>
                  <td className="p-3 text-xs">{formatDate(a.createdAt)}</td>
                  <td className="text-right p-3 space-x-2">
                    {(a.status === "triggered" || a.status === "dismissed") && (
                      <button
                        onClick={() => handleReactivate(a.id)}
                        className="text-xs text-terminal-info hover:underline"
                      >
                        Reactivate
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(a.id)}
                      className="text-xs text-terminal-negative hover:underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── Create Alert Form ── */

function CreateAlertForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [securities, setSecurities] = useState<SecurityOption[]>([]);
  const [type, setType] = useState("price_above");
  const [securityId, setSecurityId] = useState("");
  const [thresholdValue, setThresholdValue] = useState("");
  const [thresholdCurrency, setThresholdCurrency] = useState("EUR");
  const [message, setMessage] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const needsSecurity = ["price_above", "price_below", "insider_activity", "dividend_announced"].includes(type);
  const needsThreshold = ["price_above", "price_below"].includes(type);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGetRaw<{ data: SecurityOption[] }>("/securities?limit=500");
        setSecurities(res.data);
      } catch { /* */ }
    })();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message) { setError("Message is required."); return; }
    setSubmitting(true);
    setError("");
    try {
      await apiPost("/alerts", {
        type,
        security_id: securityId ? parseInt(securityId) : undefined,
        threshold_value: thresholdValue ? Math.round(parseFloat(thresholdValue) * 100) : undefined,
        threshold_currency: needsThreshold ? thresholdCurrency : undefined,
        message,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      });
      onCreated();
    } catch {
      setError("Failed to create alert.");
    }
    setSubmitting(false);
  };

  const inputCls = "w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary focus:border-terminal-accent focus:outline-none";
  const labelCls = "block text-xs text-terminal-text-secondary mb-1";

  return (
    <form onSubmit={handleSubmit} className="border border-terminal-border rounded bg-terminal-bg-secondary p-4 mb-4 space-y-3">
      {error && <div className="text-sm text-terminal-negative bg-terminal-negative/10 px-3 py-2 rounded">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label className={labelCls}>Alert Type *</label>
          <select value={type} onChange={(e) => setType(e.target.value)} className={inputCls}>
            <option value="price_above">Price Above</option>
            <option value="price_below">Price Below</option>
            <option value="insider_activity">Insider Activity</option>
            <option value="risk_breach">Risk Breach</option>
            <option value="recommendation_expiry">Rec. Expiry</option>
            <option value="dividend_announced">Dividend</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        {needsSecurity && (
          <div>
            <label className={labelCls}>Security</label>
            <select value={securityId} onChange={(e) => setSecurityId(e.target.value)} className={inputCls}>
              <option value="">All / None</option>
              {securities.map((s) => (
                <option key={s.id} value={s.id}>{s.ticker} — {s.name}</option>
              ))}
            </select>
          </div>
        )}

        {needsThreshold && (
          <>
            <div>
              <label className={labelCls}>Threshold Price</label>
              <input
                type="number"
                step="0.01"
                value={thresholdValue}
                onChange={(e) => setThresholdValue(e.target.value)}
                placeholder="e.g. 45.50"
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls}>Currency</label>
              <select value={thresholdCurrency} onChange={(e) => setThresholdCurrency(e.target.value)} className={inputCls}>
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="SEK">SEK</option>
              </select>
            </div>
          </>
        )}

        <div>
          <label className={labelCls}>Expires</label>
          <input
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            className={inputCls}
          />
        </div>
      </div>

      <div>
        <label className={labelCls}>Message *</label>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Alert description"
          className={inputCls}
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="px-4 py-1.5 bg-terminal-accent text-terminal-bg-primary text-sm rounded font-medium hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "Creating..." : "Create Alert"}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-1.5 text-sm text-terminal-text-secondary hover:text-terminal-text-primary">
          Cancel
        </button>
      </div>
    </form>
  );
}

/* ── Triggered Tab ── */

function TriggeredTab() {
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGetRaw<{ data: AlertRule[] }>("/alerts?status=triggered&limit=200");
      setAlerts(res.data);
    } catch { /* */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      await apiPost("/alerts/evaluate");
      load();
    } catch { /* */ }
    setEvaluating(false);
  };

  const handleDismiss = async (id: number) => {
    try {
      await apiPost(`/alerts/${id}/dismiss`);
      load();
    } catch { /* */ }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <span className="text-sm text-terminal-text-secondary">{alerts.length} triggered alert{alerts.length !== 1 ? "s" : ""}</span>
        <button
          onClick={handleEvaluate}
          disabled={evaluating}
          className="px-3 py-1.5 bg-terminal-bg-tertiary border border-terminal-border text-sm rounded text-terminal-text-primary hover:bg-terminal-bg-hover disabled:opacity-50"
        >
          {evaluating ? "Evaluating..." : "Evaluate Now"}
        </button>
      </div>

      {loading ? (
        <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>
      ) : alerts.length === 0 ? (
        <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
          <p className="text-terminal-text-secondary text-sm">No triggered alerts.</p>
          <p className="text-xs text-terminal-text-secondary mt-2">
            Click &quot;Evaluate Now&quot; to check all active alert rules against current data.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((a) => (
            <div
              key={a.id}
              className={`border rounded bg-terminal-bg-secondary p-4 ${
                a.type === "risk_breach" ? "border-terminal-warning" : "border-terminal-border"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded ${TYPE_COLORS[a.type] || ""}`}>
                    {TYPE_LABELS[a.type] || a.type}
                  </span>
                  {a.ticker && <span className="font-mono text-terminal-accent">{a.ticker}</span>}
                  {a.securityName && <span className="text-xs text-terminal-text-secondary">{a.securityName}</span>}
                </div>
                <div className="flex items-center gap-2">
                  {a.triggeredAt && (
                    <span className="text-xs text-terminal-text-secondary">{formatDate(a.triggeredAt)}</span>
                  )}
                  <button
                    onClick={() => handleDismiss(a.id)}
                    className="text-xs px-2 py-1 rounded bg-terminal-bg-tertiary text-terminal-text-secondary hover:text-terminal-text-primary"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
              <p className="text-sm text-terminal-text-primary">{a.message}</p>
              {a.thresholdValue && (
                <p className="text-xs text-terminal-text-secondary mt-1">
                  Threshold: {formatCurrency(a.thresholdValue, a.thresholdCurrency || "EUR")}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── History Tab ── */

function HistoryTab() {
  const [history, setHistory] = useState<AlertHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await apiGetRaw<{ data: AlertHistoryItem[]; pagination: { total: number } }>(
          "/alerts/history?limit=200"
        );
        setHistory(res.data);
        setTotal(res.pagination.total);
      } catch { /* */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-terminal-text-secondary text-sm p-4">Loading...</div>;

  if (history.length === 0) {
    return (
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-8 text-center">
        <p className="text-terminal-text-secondary text-sm">No alert trigger history yet.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-terminal-text-secondary mb-3">{total} historical trigger{total !== 1 ? "s" : ""}</p>
      <div className="border border-terminal-border rounded bg-terminal-bg-secondary overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-terminal-border text-terminal-text-secondary text-xs">
              <th className="text-left p-3">Date</th>
              <th className="text-left p-3">Alert #</th>
              <th className="text-left p-3">Message</th>
              <th className="text-right p-3">Triggered Value</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.id} className="border-b border-terminal-border/50 hover:bg-terminal-bg-tertiary">
                <td className="p-3 text-xs whitespace-nowrap">{formatDate(h.triggeredAt)}</td>
                <td className="p-3 text-xs font-mono">#{h.alertId}</td>
                <td className="p-3 text-xs">{h.message}</td>
                <td className="text-right p-3 font-mono text-xs">
                  {h.triggeredValue !== null
                    ? formatCurrency(h.triggeredValue, h.triggeredValueCurrency || "EUR")
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
