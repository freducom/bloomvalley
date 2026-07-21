"use client";

import { useState } from "react";

export type PeriodPreset = "MTD" | "1M" | "3M" | "YTD" | "1Y" | "ALL" | "CUSTOM";

export interface PeriodRange {
  from: string; // YYYY-MM-DD
  to: string;   // YYYY-MM-DD
  preset: PeriodPreset;
}

const ALL_START = "2010-01-01";

function ymd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function presetToRange(preset: Exclude<PeriodPreset, "CUSTOM">, today: Date = new Date()): PeriodRange {
  const to = ymd(today);
  let from: string;
  switch (preset) {
    case "MTD":
      from = ymd(new Date(today.getFullYear(), today.getMonth(), 1));
      break;
    case "1M": {
      const d = new Date(today); d.setMonth(d.getMonth() - 1);
      from = ymd(d);
      break;
    }
    case "3M": {
      const d = new Date(today); d.setMonth(d.getMonth() - 3);
      from = ymd(d);
      break;
    }
    case "YTD":
      from = ymd(new Date(today.getFullYear(), 0, 1));
      break;
    case "1Y": {
      const d = new Date(today); d.setFullYear(d.getFullYear() - 1);
      from = ymd(d);
      break;
    }
    case "ALL":
      from = ALL_START;
      break;
  }
  return { from, to, preset };
}

interface Props {
  value: PeriodRange;
  onChange: (r: PeriodRange) => void;
  presets?: PeriodPreset[];
}

const DEFAULT_PRESETS: PeriodPreset[] = ["MTD", "1M", "3M", "YTD", "1Y", "ALL", "CUSTOM"];
const PRESET_LABEL: Record<PeriodPreset, string> = {
  MTD: "MTD",
  "1M": "1M",
  "3M": "3M",
  YTD: "YTD",
  "1Y": "1Y",
  ALL: "All",
  CUSTOM: "Custom",
};

export function PeriodPicker({ value, onChange, presets = DEFAULT_PRESETS }: Props) {
  const [customOpen, setCustomOpen] = useState(value.preset === "CUSTOM");

  const selectPreset = (p: PeriodPreset) => {
    if (p === "CUSTOM") {
      setCustomOpen(true);
      onChange({ ...value, preset: "CUSTOM" });
      return;
    }
    setCustomOpen(false);
    onChange(presetToRange(p));
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex flex-wrap gap-1">
        {presets.map((p) => {
          const active = value.preset === p;
          return (
            <button
              key={p}
              onClick={() => selectPreset(p)}
              className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                active
                  ? "bg-terminal-accent/20 text-terminal-accent border-terminal-accent/40"
                  : "bg-terminal-bg-secondary text-terminal-text-secondary border-terminal-border hover:border-terminal-text-secondary"
              }`}
            >
              {PRESET_LABEL[p]}
            </button>
          );
        })}
      </div>

      {customOpen && (
        <div className="flex items-center gap-2 text-xs">
          <input
            type="date"
            value={value.from}
            max={value.to}
            onChange={(e) => onChange({ ...value, from: e.target.value, preset: "CUSTOM" })}
            className="bg-terminal-bg-secondary border border-terminal-border rounded px-2 py-1 text-terminal-text-primary"
          />
          <span className="text-terminal-text-secondary">→</span>
          <input
            type="date"
            value={value.to}
            min={value.from}
            onChange={(e) => onChange({ ...value, to: e.target.value, preset: "CUSTOM" })}
            className="bg-terminal-bg-secondary border border-terminal-border rounded px-2 py-1 text-terminal-text-primary"
          />
        </div>
      )}
    </div>
  );
}
