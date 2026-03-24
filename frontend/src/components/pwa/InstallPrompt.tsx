"use client";

import { useState, useEffect } from "react";
import { Download, X } from "lucide-react";

function isStandalone() {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Record<string, unknown>).standalone === true
  );
}

function isMobile() {
  if (typeof window === "undefined") return false;
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
}

function isIOS() {
  if (typeof window === "undefined") return false;
  return /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

const DISMISSED_KEY = "bv-install-dismissed";

export function InstallPrompt() {
  const [show, setShow] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<Event | null>(null);

  useEffect(() => {
    // Don't show if already installed, not mobile, or previously dismissed
    if (isStandalone() || !isMobile()) return;

    try {
      const dismissed = localStorage.getItem(DISMISSED_KEY);
      if (dismissed) {
        const ts = parseInt(dismissed, 10);
        // Don't show again for 7 days
        if (Date.now() - ts < 7 * 24 * 60 * 60 * 1000) return;
      }
    } catch { /* */ }

    // Listen for Android/Chrome install prompt
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener("beforeinstallprompt", handler);

    // Show after 1 minute
    const timer = setTimeout(() => setShow(true), 60_000);

    return () => {
      window.removeEventListener("beforeinstallprompt", handler);
      clearTimeout(timer);
    };
  }, []);

  const dismiss = () => {
    setShow(false);
    try {
      localStorage.setItem(DISMISSED_KEY, String(Date.now()));
    } catch { /* */ }
  };

  const handleInstall = async () => {
    if (deferredPrompt && "prompt" in deferredPrompt) {
      (deferredPrompt as { prompt: () => void }).prompt();
      dismiss();
    }
  };

  if (!show) return null;

  return (
    <div className="fixed bottom-4 left-4 right-4 z-[100] animate-in slide-in-from-bottom">
      <div className="bg-terminal-bg-secondary border border-terminal-border rounded-lg p-4 shadow-lg">
        <div className="flex items-start gap-3">
          <div className="shrink-0 p-2 bg-terminal-accent/20 rounded-lg">
            <Download size={20} className="text-terminal-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-terminal-text-primary">
              Install Bloomvalley
            </p>
            {isIOS() ? (
              <p className="text-xs text-terminal-text-secondary mt-1">
                Tap the share button, then &quot;Add to Home Screen&quot; for
                offline access to your portfolio.
              </p>
            ) : (
              <p className="text-xs text-terminal-text-secondary mt-1">
                Add to your home screen for offline access to your portfolio.
              </p>
            )}
            {deferredPrompt && (
              <button
                onClick={handleInstall}
                className="mt-2 px-3 py-1.5 text-xs font-medium rounded bg-terminal-accent text-white hover:bg-terminal-accent/80 transition-colors"
              >
                Install
              </button>
            )}
          </div>
          <button
            onClick={dismiss}
            className="shrink-0 p-1 text-terminal-text-tertiary hover:text-terminal-text-primary transition-colors"
            aria-label="Dismiss"
          >
            <X size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
