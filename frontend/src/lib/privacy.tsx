"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";

interface PrivacyContextType {
  privacyMode: boolean;
  togglePrivacy: () => void;
}

const PrivacyContext = createContext<PrivacyContextType>({
  privacyMode: false,
  togglePrivacy: () => {},
});

const STORAGE_KEY = "bloomvalley-privacy-mode";

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyMode] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "true") setPrivacyMode(true);
    } catch {}
  }, []);

  const togglePrivacy = useCallback(() => {
    setPrivacyMode((prev) => {
      const next = !prev;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  // Global shortcut: Cmd+Shift+P
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "p") {
        e.preventDefault();
        togglePrivacy();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [togglePrivacy]);

  return (
    <PrivacyContext.Provider value={{ privacyMode, togglePrivacy }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function usePrivacy() {
  return useContext(PrivacyContext);
}

/**
 * Wrapper that blurs its children when privacy mode is active.
 * Use for monetary amounts, quantities, share counts.
 */
export function Private({ children }: { children: ReactNode }) {
  const { privacyMode } = usePrivacy();
  if (!privacyMode) return <>{children}</>;
  return (
    <span className="select-none" style={{ filter: "blur(8px)", WebkitFilter: "blur(8px)" }}>
      {children}
    </span>
  );
}
