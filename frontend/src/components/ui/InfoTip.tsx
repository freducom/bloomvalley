"use client";

/**
 * (i) hover tooltip for explaining financial terms in the UI.
 * Usage: <InfoTip text="Explanation of the term" />
 */
export function InfoTip({ text }: { text: string }) {
  return (
    <span className="relative group">
      <span className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-terminal-text-tertiary text-terminal-text-tertiary text-[10px] cursor-help leading-none">
        i
      </span>
      <span className="absolute left-6 top-0 z-10 hidden group-hover:block w-72 p-2 text-xs text-terminal-text-primary bg-terminal-bg-tertiary border border-terminal-border rounded shadow-md whitespace-normal">
        {text}
      </span>
    </span>
  );
}
