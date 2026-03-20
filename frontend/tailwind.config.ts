import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: {
            primary: "#0A0E17",
            secondary: "#111827",
            tertiary: "#1F2937",
            hover: "#374151",
          },
          border: {
            DEFAULT: "#1F2937",
            subtle: "#111827",
          },
          text: {
            primary: "#F9FAFB",
            secondary: "#9CA3AF",
            tertiary: "#6B7280",
          },
          positive: "#22C55E",
          "positive-muted": "#166534",
          negative: "#EF4444",
          "negative-muted": "#7F1D1D",
          warning: "#F59E0B",
          "warning-muted": "#78350F",
          info: "#3B82F6",
          "info-muted": "#1E3A5F",
          accent: "#8B5CF6",
          asset: {
            stocks: "#3B82F6",
            etfs: "#8B5CF6",
            bonds: "#22D3EE",
            crypto: "#F59E0B",
            cash: "#6B7280",
          },
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        xs: ["10px", "14px"],
        sm: ["12px", "16px"],
        base: ["14px", "20px"],
        lg: ["18px", "28px"],
        xl: ["20px", "28px"],
        "2xl": ["24px", "32px"],
        "3xl": ["30px", "36px"],
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0,0,0,0.3)",
        md: "0 4px 12px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};

export default config;
