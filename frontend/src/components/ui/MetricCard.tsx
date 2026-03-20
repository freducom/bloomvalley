"use client";

interface MetricCardProps {
  label: string;
  value: string;
  change?: string;
  changeType?: "positive" | "negative" | "neutral";
  size?: "sm" | "md" | "lg";
  onClick?: () => void;
}

export function MetricCard({
  label,
  value,
  change,
  changeType = "neutral",
  size = "md",
  onClick,
}: MetricCardProps) {
  const changeColor = {
    positive: "text-terminal-positive",
    negative: "text-terminal-negative",
    neutral: "text-terminal-text-tertiary",
  }[changeType];

  const changePrefix = {
    positive: "\u25B2 ",
    negative: "\u25BC ",
    neutral: "",
  }[changeType];

  const valueSize = {
    sm: "text-lg",
    md: "text-xl",
    lg: "text-2xl",
  }[size];

  const minHeight = {
    sm: "min-h-[72px]",
    md: "min-h-[88px]",
    lg: "min-h-[120px]",
  }[size];

  return (
    <div
      onClick={onClick}
      className={`
        bg-terminal-bg-secondary border border-terminal-border rounded-md p-3
        transition-colors duration-150
        ${onClick ? "cursor-pointer hover:bg-terminal-bg-tertiary" : ""}
        ${minHeight}
      `}
    >
      <div className="text-sm font-medium text-terminal-text-secondary mb-1">
        {label}
      </div>
      <div className={`font-mono font-semibold text-terminal-text-primary ${valueSize}`}>
        {value}
      </div>
      {(size === "md" || size === "lg") && change && (
        <div className={`font-mono text-sm mt-1 ${changeColor}`}>
          {changePrefix}
          {change}
        </div>
      )}
      {size === "lg" && (
        <div className="mt-2 h-12 bg-terminal-bg-tertiary rounded-sm flex items-center justify-center">
          <span className="text-xs text-terminal-text-tertiary">Sparkline</span>
        </div>
      )}
    </div>
  );
}
