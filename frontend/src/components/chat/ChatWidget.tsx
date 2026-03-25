"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageSquare, X, Send, Trash2, Loader2, Maximize2, Minimize2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  role: "user" | "assistant";
  content: string;
}

function useIsMobile() {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const check = () => setMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return mobile;
}

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const isMobile = useIsMobile();
  const [viewportHeight, setViewportHeight] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // On mobile, always use fullscreen
  const isExpanded = fullscreen || isMobile;

  // Track visual viewport height for iOS keyboard handling
  useEffect(() => {
    if (!isMobile) return;
    const vv = window.visualViewport;
    if (!vv) return;
    const onResize = () => setViewportHeight(vv.height);
    onResize();
    vv.addEventListener("resize", onResize);
    return () => vv.removeEventListener("resize", onResize);
  }, [isMobile, open]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: Message = { role: "user", content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setStreaming(true);

    // Add empty assistant message for streaming
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/v1/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages,
          page_url: window.location.pathname,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6);
          try {
            const event = JSON.parse(jsonStr);
            if (event.type === "content" && event.text) {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + event.text,
                  };
                }
                return updated;
              });
            } else if (event.type === "error") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant") {
                  updated[updated.length - 1] = {
                    ...last,
                    content: `Error: ${event.text}`,
                  };
                }
                return updated;
              });
            }
          } catch {
            // skip malformed JSON
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === "assistant" && !last.content) {
          updated[updated.length - 1] = {
            ...last,
            content: "Failed to get response. Check that the backend is running.",
          };
        }
        return updated;
      });
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    if (streaming) {
      abortRef.current?.abort();
    }
    setMessages([]);
    setStreaming(false);
  };

  return (
    <>
      {/* Chat toggle button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-14 right-4 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-terminal-accent shadow-md hover:bg-terminal-accent/80 transition-colors"
          aria-label="Open chat"
        >
          <MessageSquare className="h-5 w-5 text-white" />
        </button>
      )}

      {/* Backdrop for fullscreen / mobile */}
      {open && isExpanded && (
        <div
          className="fixed inset-0 z-50 bg-black/60"
          onClick={() => { if (!isMobile) setFullscreen(false); }}
        />
      )}

      {/* Chat panel */}
      {open && (
        <div className={`fixed z-50 flex flex-col border border-terminal-border bg-terminal-bg-secondary shadow-md transition-all duration-200 ${
          isExpanded
            ? isMobile
              ? "inset-0 w-full"
              : "inset-0 m-auto w-[90vw] h-[90vh] rounded-lg"
            : "bottom-14 right-4 w-96 rounded-lg"
        }`}
          style={
            isExpanded && isMobile
              ? {
                  height: viewportHeight ? `${viewportHeight}px` : "100dvh",
                  top: 0,
                  left: 0,
                  right: 0,
                  paddingTop: "env(safe-area-inset-top)",
                  paddingLeft: "env(safe-area-inset-left)",
                  paddingRight: "env(safe-area-inset-right)",
                }
              : isExpanded
                ? undefined
                : { height: "min(600px, calc(100vh - 120px))" }
          }
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-terminal-border px-4 py-3 shrink-0">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-terminal-accent" />
              <span className="text-sm font-medium text-terminal-text-primary">
                Bloomvalley Chat
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={clearChat}
                className="rounded p-1.5 text-terminal-text-tertiary hover:bg-terminal-bg-hover hover:text-terminal-text-secondary transition-colors"
                aria-label="Clear chat"
                title="Clear chat"
              >
                <Trash2 className="h-4 w-4" />
              </button>
              {/* Hide fullscreen toggle on mobile — it's always fullscreen */}
              <button
                onClick={() => setFullscreen((f) => !f)}
                className="hidden md:block rounded p-1.5 text-terminal-text-tertiary hover:bg-terminal-bg-hover hover:text-terminal-text-secondary transition-colors"
                aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen"}
                title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
              <button
                onClick={() => { setOpen(false); setFullscreen(false); }}
                className="rounded p-1.5 text-terminal-text-tertiary hover:bg-terminal-bg-hover hover:text-terminal-text-secondary transition-colors"
                aria-label="Close chat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <p className="text-sm text-terminal-text-tertiary text-center">
                  Ask me about your portfolio, markets, or investment strategy.
                </p>
              </div>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    msg.role === "user"
                      ? "bg-terminal-accent/20 text-terminal-text-primary"
                      : "bg-terminal-bg-tertiary text-terminal-text-primary"
                  }`}
                >
                  {msg.role === "assistant" && !msg.content && streaming && i === messages.length - 1 ? (
                    <Loader2 className="h-4 w-4 animate-spin text-terminal-text-tertiary" />
                  ) : msg.role === "assistant" ? (
                    <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-pre:bg-terminal-bg-primary prose-pre:text-terminal-text-primary prose-code:text-terminal-accent prose-strong:text-terminal-text-primary prose-a:text-terminal-info">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input — env(safe-area-inset-bottom) handles iOS home bar */}
          <div className="border-t border-terminal-border p-3 shrink-0" style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}>
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type a message..."
                rows={1}
                className="flex-1 resize-none rounded-md border border-terminal-border bg-terminal-bg-primary px-3 py-2 text-sm text-terminal-text-primary placeholder:text-terminal-text-tertiary focus:border-terminal-accent focus:outline-none"
                style={{ maxHeight: "120px" }}
                disabled={streaming}
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || streaming}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-terminal-accent text-white hover:bg-terminal-accent/80 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="Send message"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
