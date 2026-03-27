"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost, apiPut, apiDelete, apiGetRaw } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { Private } from "@/lib/privacy";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const gfmOptions = { singleTilde: false };

interface ResearchNote {
  id: number;
  securityId: number;
  ticker: string;
  securityName: string;
  sector: string | null;
  assetClass: string | null;
  title: string;
  thesis: string | null;
  bullCase: string | null;
  bearCase: string | null;
  baseCase: string | null;
  intrinsicValueCents: number | null;
  intrinsicValueCurrency: string | null;
  marginOfSafetyPct: number | null;
  currentPriceCents: number | null;
  moatRating: string | null;
  tags: string[];
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

interface SecurityOption {
  id: number;
  ticker: string;
  name: string;
  currency: string;
}

interface NoteForm {
  securityId: number | null;
  title: string;
  thesis: string;
  bullCase: string;
  bearCase: string;
  baseCase: string;
  intrinsicValueCents: string;
  intrinsicValueCurrency: string;
  marginOfSafetyPct: string;
  moatRating: string;
  tags: string;
}

const EMPTY_FORM: NoteForm = {
  securityId: null,
  title: "",
  thesis: "",
  bullCase: "",
  bearCase: "",
  baseCase: "",
  intrinsicValueCents: "",
  intrinsicValueCurrency: "EUR",
  marginOfSafetyPct: "",
  moatRating: "",
  tags: "",
};

const MOAT_OPTIONS = [
  { value: "", label: "Not rated" },
  { value: "none", label: "None" },
  { value: "narrow", label: "Narrow" },
  { value: "wide", label: "Wide" },
];

const PROSE_CLASSES = "text-sm text-terminal-text-primary leading-relaxed prose prose-invert prose-sm max-w-none prose-table:border-collapse prose-th:border prose-th:border-terminal-border prose-th:px-2 prose-th:py-1 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-th:text-terminal-text-primary prose-th:bg-terminal-bg-secondary prose-td:border prose-td:border-terminal-border prose-td:px-2 prose-td:py-1 prose-td:text-xs prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-headings:text-terminal-text-primary prose-headings:mt-3 prose-headings:mb-1 prose-strong:text-terminal-text-primary prose-code:text-terminal-accent";

const MOAT_COLORS: Record<string, string> = {
  wide: "text-green-400",
  narrow: "text-yellow-400",
  none: "text-red-400",
};

export default function ResearchPage() {
  const [notes, setNotes] = useState<ResearchNote[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<NoteForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [securities, setSecurities] = useState<SecurityOption[]>([]);
  const [secSearch, setSecSearch] = useState("");
  const [showSecDropdown, setShowSecDropdown] = useState(false);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [filterMoat, setFilterMoat] = useState("");
  const [filterTag, setFilterTag] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  const selectedNote = notes.find((n) => n.id === selectedId);

  const loadNotes = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterMoat) params.set("moatRating", filterMoat);
      if (filterTag) params.set("tag", filterTag);
      if (searchQuery) params.set("q", searchQuery);
      if (!showArchived) params.set("isActive", "true");
      params.set("limit", "500");
      const qs = params.toString();
      const res = await apiGetRaw<{
        data: ResearchNote[];
        pagination: { total: number };
      }>(`/research/notes${qs ? `?${qs}` : ""}`);
      setNotes(res.data);
      setTotal(res.pagination.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [filterMoat, filterTag, searchQuery, showArchived]);

  const loadTags = async () => {
    try {
      const tags = await apiGet<string[]>("/research/tags");
      setAllTags(tags);
    } catch {
      /* ignore */
    }
  };

  const loadSecurities = async () => {
    try {
      const secs = await apiGet<SecurityOption[]>("/securities");
      setSecurities(secs);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    loadNotes();
    loadTags();
    loadSecurities();
  }, [loadNotes]);

  const noteToForm = (note: ResearchNote): NoteForm => ({
    securityId: note.securityId,
    title: note.title,
    thesis: note.thesis || "",
    bullCase: note.bullCase || "",
    bearCase: note.bearCase || "",
    baseCase: note.baseCase || "",
    intrinsicValueCents: note.intrinsicValueCents
      ? (note.intrinsicValueCents / 100).toFixed(2)
      : "",
    intrinsicValueCurrency: note.intrinsicValueCurrency || "EUR",
    marginOfSafetyPct: note.marginOfSafetyPct?.toString() || "",
    moatRating: note.moatRating || "",
    tags: note.tags.join(", "),
  });

  const startCreate = () => {
    setCreating(true);
    setEditing(false);
    setSelectedId(null);
    setForm(EMPTY_FORM);
    setSecSearch("");
  };

  const startEdit = () => {
    if (!selectedNote) return;
    setEditing(true);
    setCreating(false);
    setForm(noteToForm(selectedNote));
  };

  const cancelEdit = () => {
    setEditing(false);
    setCreating(false);
    setForm(EMPTY_FORM);
  };

  const handleSave = async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      const tags = form.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const ivCents = form.intrinsicValueCents
        ? Math.round(parseFloat(form.intrinsicValueCents) * 100)
        : null;
      const mosPct = form.marginOfSafetyPct
        ? parseFloat(form.marginOfSafetyPct)
        : null;

      if (creating) {
        if (!form.securityId) return;
        await apiPost("/research/notes", {
          securityId: form.securityId,
          title: form.title,
          thesis: form.thesis || null,
          bullCase: form.bullCase || null,
          bearCase: form.bearCase || null,
          baseCase: form.baseCase || null,
          intrinsicValueCents: ivCents,
          intrinsicValueCurrency: form.intrinsicValueCurrency || null,
          marginOfSafetyPct: mosPct,
          moatRating: form.moatRating || null,
          tags: tags.length ? tags : null,
        });
      } else if (editing && selectedId) {
        await apiPut(`/research/notes/${selectedId}`, {
          title: form.title,
          thesis: form.thesis || null,
          bullCase: form.bullCase || null,
          bearCase: form.bearCase || null,
          baseCase: form.baseCase || null,
          intrinsicValueCents: ivCents,
          intrinsicValueCurrency: form.intrinsicValueCurrency || null,
          marginOfSafetyPct: mosPct,
          moatRating: form.moatRating || null,
          tags,
        });
      }
      setCreating(false);
      setEditing(false);
      await loadNotes();
      await loadTags();
    } catch (e) {
      console.error("Save failed:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await apiDelete(`/research/notes/${id}`);
      if (selectedId === id) {
        setSelectedId(null);
        setEditing(false);
      }
      await loadNotes();
    } catch (e) {
      console.error("Delete failed:", e);
    }
  };

  const filteredSecurities = securities.filter(
    (s) =>
      secSearch.length >= 1 &&
      (s.ticker.toLowerCase().includes(secSearch.toLowerCase()) ||
        s.name.toLowerCase().includes(secSearch.toLowerCase()))
  );

  const isFormMode = creating || editing;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Research</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-terminal-text-secondary">
            {total} note{total !== 1 ? "s" : ""}
          </span>
          <button
            onClick={startCreate}
            className="px-4 py-2 bg-terminal-accent text-white rounded text-sm font-medium hover:opacity-90"
          >
            + New Note
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          placeholder="Search notes..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary w-60"
        />
        <select
          value={filterMoat}
          onChange={(e) => setFilterMoat(e.target.value)}
          className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
        >
          <option value="">All moats</option>
          <option value="wide">Wide moat</option>
          <option value="narrow">Narrow moat</option>
          <option value="none">No moat</option>
        </select>
        {allTags.length > 0 && (
          <select
            value={filterTag}
            onChange={(e) => setFilterTag(e.target.value)}
            className="px-3 py-1.5 bg-terminal-bg-secondary border border-terminal-border rounded text-sm text-terminal-text-primary"
          >
            <option value="">All tags</option>
            {allTags.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-sm text-terminal-text-secondary">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="accent-terminal-accent"
          />
          Archived
        </label>
      </div>

      {/* Mobile: show list OR detail, not both */}
      {/* Desktop: side-by-side grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left panel — note list (hidden on mobile when viewing a note) */}
        <div className={`lg:col-span-1 space-y-2 max-h-[calc(100vh-220px)] overflow-y-auto pr-1 ${
          (selectedNote || isFormMode) ? "hidden lg:block" : ""
        }`}>
          {loading ? (
            <div className="text-terminal-text-secondary text-sm p-4">
              Loading...
            </div>
          ) : notes.length === 0 ? (
            <div className="text-terminal-text-secondary text-sm p-4 border border-terminal-border rounded bg-terminal-bg-secondary">
              No research notes yet. Click &quot;+ New Note&quot; to start.
            </div>
          ) : (
            notes.map((note) => (
              <button
                key={note.id}
                onClick={() => {
                  setSelectedId(note.id);
                  setEditing(false);
                  setCreating(false);
                }}
                className={`w-full text-left p-3 rounded border transition-colors ${
                  selectedId === note.id
                    ? "border-terminal-accent bg-terminal-bg-tertiary"
                    : "border-terminal-border bg-terminal-bg-secondary hover:border-terminal-text-secondary"
                } ${!note.isActive ? "opacity-50" : ""}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono text-terminal-accent">
                    {note.ticker}
                  </span>
                  {note.moatRating && (
                    <span
                      className={`text-xs font-medium ${
                        MOAT_COLORS[note.moatRating] ||
                        "text-terminal-text-secondary"
                      }`}
                    >
                      {note.moatRating.charAt(0).toUpperCase() +
                        note.moatRating.slice(1)}{" "}
                      moat
                    </span>
                  )}
                </div>
                <div className="text-sm font-medium text-terminal-text-primary truncate">
                  {note.title}
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs text-terminal-text-secondary">
                    {note.securityName}
                  </span>
                  {note.marginOfSafetyPct !== null && (
                    <span
                      className={`text-xs font-mono ${
                        note.marginOfSafetyPct >= 0
                          ? "text-terminal-positive"
                          : "text-terminal-negative"
                      }`}
                    >
                      MoS {note.marginOfSafetyPct > 0 ? "+" : ""}
                      {note.marginOfSafetyPct.toFixed(1)}%
                    </span>
                  )}
                </div>
                {note.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {note.tags.slice(0, 4).map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-terminal-bg-primary text-terminal-text-secondary"
                      >
                        {tag}
                      </span>
                    ))}
                    {note.tags.length > 4 && (
                      <span className="text-[10px] text-terminal-text-secondary">
                        +{note.tags.length - 4}
                      </span>
                    )}
                  </div>
                )}
              </button>
            ))
          )}
        </div>

        {/* Right panel — detail or form (hidden on mobile when no note selected) */}
        <div className={`lg:col-span-2 ${
          !selectedNote && !isFormMode ? "hidden lg:block" : ""
        }`}>
          {/* Back button on mobile */}
          {(selectedNote || isFormMode) && (
            <button
              onClick={() => {
                setSelectedId(null);
                setEditing(false);
                setCreating(false);
              }}
              className="lg:hidden mb-3 text-sm text-terminal-accent hover:underline font-mono"
            >
              &larr; Back to list
            </button>
          )}
          {isFormMode ? (
            <NoteForm
              form={form}
              setForm={setForm}
              creating={creating}
              saving={saving}
              onSave={handleSave}
              onCancel={cancelEdit}
              securities={filteredSecurities}
              secSearch={secSearch}
              setSecSearch={setSecSearch}
              showSecDropdown={showSecDropdown}
              setShowSecDropdown={setShowSecDropdown}
            />
          ) : selectedNote ? (
            <NoteDetail
              note={selectedNote}
              onEdit={startEdit}
              onDelete={() => handleDelete(selectedNote.id)}
            />
          ) : (
            <div className="flex items-center justify-center h-64 border border-terminal-border rounded bg-terminal-bg-secondary">
              <p className="text-terminal-text-secondary text-sm">
                Select a note or create a new one
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Note Detail View ── */

function NoteDetail({
  note,
  onEdit,
  onDelete,
}: {
  note: ResearchNote;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-5 space-y-5 max-h-[calc(100vh-220px)] overflow-y-auto">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-terminal-accent text-lg">
              {note.ticker}
            </span>
            <span className="text-terminal-text-secondary text-sm">
              {note.securityName}
            </span>
            {note.sector && (
              <span className="text-xs px-2 py-0.5 rounded bg-terminal-bg-tertiary text-terminal-text-secondary">
                {note.sector}
              </span>
            )}
          </div>
          <h2 className="text-xl font-bold text-terminal-text-primary">
            {note.title}
          </h2>
          {!note.isActive && (
            <span className="text-xs text-terminal-negative">Archived</span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onEdit}
            className="px-3 py-1.5 text-sm border border-terminal-border rounded hover:border-terminal-accent text-terminal-text-secondary hover:text-terminal-accent"
          >
            Edit
          </button>
          <button
            onClick={onDelete}
            className="px-3 py-1.5 text-sm border border-terminal-border rounded hover:border-terminal-negative text-terminal-text-secondary hover:text-terminal-negative"
          >
            Archive
          </button>
        </div>
      </div>

      {/* Valuation metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {note.moatRating && (
          <MetricBox
            label="Moat"
            value={
              note.moatRating.charAt(0).toUpperCase() +
              note.moatRating.slice(1)
            }
            valueClass={
              MOAT_COLORS[note.moatRating] || "text-terminal-text-primary"
            }
          />
        )}
        {note.intrinsicValueCents !== null && (
          <MetricBox
            label="Intrinsic Value"
            value={<Private>{formatCurrency(
              note.intrinsicValueCents,
              note.intrinsicValueCurrency || "EUR"
            )}</Private>}
          />
        )}
        {note.currentPriceCents !== null && (
          <MetricBox
            label="Current Price"
            value={formatCurrency(
              note.currentPriceCents,
              note.intrinsicValueCurrency || "EUR"
            )}
          />
        )}
        {note.marginOfSafetyPct !== null && (
          <MetricBox
            label="Margin of Safety"
            value={`${note.marginOfSafetyPct > 0 ? "+" : ""}${note.marginOfSafetyPct.toFixed(1)}%`}
            valueClass={
              note.marginOfSafetyPct >= 20
                ? "text-terminal-positive"
                : note.marginOfSafetyPct >= 0
                  ? "text-terminal-warning"
                  : "text-terminal-negative"
            }
          />
        )}
      </div>

      {/* Thesis */}
      {note.thesis && (
        <div>
          <h3 className="text-sm font-semibold text-terminal-text-secondary mb-1">
            Investment Thesis
          </h3>
          <div className={PROSE_CLASSES}>
            <ReactMarkdown remarkPlugins={[[remarkGfm, gfmOptions]]}>{note.thesis}</ReactMarkdown>
          </div>
        </div>
      )}

      {/* Bull / Base / Bear cases */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {note.bullCase && (
          <CaseCard label="Bull Case" text={note.bullCase} color="border-terminal-positive" />
        )}
        {note.baseCase && (
          <CaseCard label="Base Case" text={note.baseCase} color="border-terminal-info" />
        )}
        {note.bearCase && (
          <CaseCard label="Bear Case" text={note.bearCase} color="border-terminal-negative" />
        )}
      </div>

      {/* Tags */}
      {note.tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {note.tags.map((tag) => (
            <span
              key={tag}
              className="text-xs px-2 py-1 rounded bg-terminal-bg-tertiary text-terminal-text-secondary border border-terminal-border"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-terminal-text-secondary pt-2 border-t border-terminal-border">
        Created {new Date(note.createdAt).toLocaleDateString()} · Updated{" "}
        {new Date(note.updatedAt).toLocaleDateString()}
      </div>
    </div>
  );
}

/* ── Note Form ── */

function NoteForm({
  form,
  setForm,
  creating,
  saving,
  onSave,
  onCancel,
  securities,
  secSearch,
  setSecSearch,
  showSecDropdown,
  setShowSecDropdown,
}: {
  form: NoteForm;
  setForm: (f: NoteForm) => void;
  creating: boolean;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
  securities: SecurityOption[];
  secSearch: string;
  setSecSearch: (s: string) => void;
  showSecDropdown: boolean;
  setShowSecDropdown: (b: boolean) => void;
}) {
  const selectedSec = securities.find((s) => s.id === form.securityId);

  return (
    <div className="border border-terminal-border rounded bg-terminal-bg-secondary p-5 space-y-4 max-h-[calc(100vh-220px)] overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-terminal-text-primary">
          {creating ? "New Research Note" : "Edit Note"}
        </h2>
        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm border border-terminal-border rounded text-terminal-text-secondary hover:text-terminal-text-primary"
          >
            Cancel
          </button>
          <button
            onClick={onSave}
            disabled={saving || !form.title.trim() || (creating && !form.securityId)}
            className="px-4 py-1.5 text-sm bg-terminal-accent text-white rounded font-medium hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      {/* Security selector (create only) */}
      {creating && (
        <div className="relative">
          <label className="block text-xs text-terminal-text-secondary mb-1">
            Security
          </label>
          {form.securityId ? (
            <div className="flex items-center gap-2">
              <span className="font-mono text-terminal-accent">
                {selectedSec?.ticker}
              </span>
              <span className="text-sm text-terminal-text-secondary">
                {selectedSec?.name}
              </span>
              <button
                onClick={() => {
                  setForm({ ...form, securityId: null });
                  setSecSearch("");
                }}
                className="text-xs text-terminal-negative ml-2"
              >
                change
              </button>
            </div>
          ) : (
            <>
              <input
                type="text"
                placeholder="Search ticker or name..."
                value={secSearch}
                onChange={(e) => {
                  setSecSearch(e.target.value);
                  setShowSecDropdown(true);
                }}
                onFocus={() => setShowSecDropdown(true)}
                className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary"
              />
              {showSecDropdown && securities.length > 0 && secSearch.length >= 1 && (
                <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto bg-terminal-bg-tertiary border border-terminal-border rounded shadow-lg">
                  {securities
                    .filter(
                      (s) =>
                        s.ticker.toLowerCase().includes(secSearch.toLowerCase()) ||
                        s.name.toLowerCase().includes(secSearch.toLowerCase())
                    )
                    .slice(0, 20)
                    .map((s) => (
                      <button
                        key={s.id}
                        onClick={() => {
                          setForm({
                            ...form,
                            securityId: s.id,
                            intrinsicValueCurrency: s.currency,
                          });
                          setSecSearch(s.ticker);
                          setShowSecDropdown(false);
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-terminal-bg-secondary text-sm"
                      >
                        <span className="font-mono text-terminal-accent mr-2">
                          {s.ticker}
                        </span>
                        <span className="text-terminal-text-secondary">
                          {s.name}
                        </span>
                      </button>
                    ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Title */}
      <div>
        <label className="block text-xs text-terminal-text-secondary mb-1">
          Title
        </label>
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="e.g. Q4 2025 Earnings Analysis"
          className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary"
        />
      </div>

      {/* Moat rating */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <label className="block text-xs text-terminal-text-secondary mb-1">
            Moat Rating
          </label>
          <select
            value={form.moatRating}
            onChange={(e) => setForm({ ...form, moatRating: e.target.value })}
            className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary"
          >
            {MOAT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-terminal-text-secondary mb-1">
            Intrinsic Value
          </label>
          <input
            type="number"
            step="0.01"
            value={form.intrinsicValueCents}
            onChange={(e) =>
              setForm({ ...form, intrinsicValueCents: e.target.value })
            }
            placeholder="e.g. 45.00"
            className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary font-mono placeholder:text-terminal-text-secondary"
          />
        </div>
        <div>
          <label className="block text-xs text-terminal-text-secondary mb-1">
            Currency
          </label>
          <select
            value={form.intrinsicValueCurrency}
            onChange={(e) =>
              setForm({ ...form, intrinsicValueCurrency: e.target.value })
            }
            className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary"
          >
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
            <option value="GBP">GBP</option>
            <option value="SEK">SEK</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-terminal-text-secondary mb-1">
            Tags
          </label>
          <input
            type="text"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
            placeholder="dividend, value, ..."
            className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary"
          />
        </div>
      </div>

      {/* Thesis */}
      <div>
        <label className="block text-xs text-terminal-text-secondary mb-1">
          Investment Thesis
        </label>
        <textarea
          rows={3}
          value={form.thesis}
          onChange={(e) => setForm({ ...form, thesis: e.target.value })}
          placeholder="Why this security? What's the core investment thesis?"
          className="w-full px-3 py-2 bg-terminal-bg-primary border border-terminal-border rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary resize-y"
        />
      </div>

      {/* Bull / Base / Bear */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-terminal-positive mb-1">
            Bull Case
          </label>
          <textarea
            rows={4}
            value={form.bullCase}
            onChange={(e) => setForm({ ...form, bullCase: e.target.value })}
            placeholder="Best-case scenario..."
            className="w-full px-3 py-2 bg-terminal-bg-primary border-l-2 border border-terminal-positive/30 border-l-terminal-positive rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary resize-y"
          />
        </div>
        <div>
          <label className="block text-xs text-terminal-info mb-1">
            Base Case
          </label>
          <textarea
            rows={4}
            value={form.baseCase}
            onChange={(e) => setForm({ ...form, baseCase: e.target.value })}
            placeholder="Most likely scenario..."
            className="w-full px-3 py-2 bg-terminal-bg-primary border-l-2 border border-terminal-info/30 border-l-terminal-info rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary resize-y"
          />
        </div>
        <div>
          <label className="block text-xs text-terminal-negative mb-1">
            Bear Case
          </label>
          <textarea
            rows={4}
            value={form.bearCase}
            onChange={(e) => setForm({ ...form, bearCase: e.target.value })}
            placeholder="Worst-case scenario..."
            className="w-full px-3 py-2 bg-terminal-bg-primary border-l-2 border border-terminal-negative/30 border-l-terminal-negative rounded text-sm text-terminal-text-primary placeholder:text-terminal-text-secondary resize-y"
          />
        </div>
      </div>
    </div>
  );
}

/* ── Helper Components ── */

function MetricBox({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: React.ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="p-3 rounded bg-terminal-bg-tertiary border border-terminal-border">
      <div className="text-xs text-terminal-text-secondary mb-0.5">
        {label}
      </div>
      <div
        className={`text-sm font-mono font-medium ${
          valueClass || "text-terminal-text-primary"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function CaseCard({
  label,
  text,
  color,
}: {
  label: string;
  text: string;
  color: string;
}) {
  return (
    <div
      className={`p-3 rounded bg-terminal-bg-tertiary border-l-2 ${color} border border-terminal-border`}
    >
      <div className="text-xs font-semibold text-terminal-text-secondary mb-1">
        {label}
      </div>
      <div className={PROSE_CLASSES}>
        <ReactMarkdown remarkPlugins={[[remarkGfm, gfmOptions]]}>{text}</ReactMarkdown>
      </div>
    </div>
  );
}
