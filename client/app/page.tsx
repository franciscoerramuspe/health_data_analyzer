"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type HTMLAttributes,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type ToolTrace = { name: string; args: Record<string, unknown>; result: unknown };
type Msg = { role: "user" | "model"; text: string; trace?: ToolTrace[] };

const STORAGE_KEY = "health-chat:messages";

const EXAMPLES = [
  "What's my average HRV in the last 30 days?",
  "Does drinking caffeine affect my sleep?",
  "What were my best and worst recovery days ever?",
  "Am I overtraining lately?",
];

export default function Home() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load saved conversation on first mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setMessages(JSON.parse(raw));
    } catch {}
    setHydrated(true);
  }, []);

  // Persist on every change (after hydration so we don't wipe on first load)
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {}
  }, [messages, hydrated]);

  // Auto-scroll to bottom when messages or loading state change
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  // Refocus input when we stop loading
  useEffect(() => {
    if (!loading) inputRef.current?.focus();
  }, [loading]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    const next: Msg[] = [...messages, { role: "user", text: content }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: next.map((m) => ({ role: m.role, text: m.text })),
        }),
      });
      const data = await res.json();
      setMessages([
        ...next,
        {
          role: "model",
          text: data.text ?? `**Error:** ${data.error ?? "unknown"}`,
          trace: data.trace,
        },
      ]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setMessages([
        ...next,
        { role: "model", text: `**Network error:** ${msg}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    if (!confirm("Clear the whole conversation?")) return;
    setMessages([]);
  }

  const hasMessages = messages.length > 0;

  return (
    <main
      style={{
        maxWidth: 760,
        margin: "0 auto",
        padding: "0 16px",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 0",
          borderBottom: "1px solid #1f1f22",
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>health chat</div>
          <div style={{ fontSize: 12, opacity: 0.5, marginTop: 2 }}>
            grounded in your Whoop data · gemini-3.1-flash-lite
          </div>
        </div>
        {hasMessages && (
          <button
            onClick={reset}
            style={{
              padding: "6px 10px",
              background: "transparent",
              border: "1px solid #333",
              borderRadius: 6,
              color: "#aaa",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            new chat
          </button>
        )}
      </header>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "20px 0",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {!hasMessages && hydrated && <EmptyState onPick={(q) => send(q)} />}

        {messages.map((m, i) => (
          <Message key={i} msg={m} />
        ))}

        {loading && (
          <div
            style={{
              padding: "10px 14px",
              fontSize: 13,
              opacity: 0.6,
              fontStyle: "italic",
            }}
          >
            thinking…
          </div>
        )}
      </div>

      <div
        style={{
          display: "flex",
          gap: 8,
          padding: "12px 0 20px",
          flexShrink: 0,
          borderTop: "1px solid #1f1f22",
        }}
      >
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask about your data… (Shift+Enter for newline)"
          disabled={loading}
          rows={1}
          style={{
            flex: 1,
            padding: "10px 12px",
            background: "#1a1a1c",
            border: "1px solid #333",
            borderRadius: 8,
            color: "#e5e5e5",
            fontSize: 14,
            resize: "none",
            fontFamily: "inherit",
            lineHeight: 1.4,
            maxHeight: 160,
          }}
        />
        <button
          onClick={() => send()}
          disabled={loading || !input.trim()}
          style={{
            padding: "10px 18px",
            background: "#2a5a8a",
            border: "none",
            borderRadius: 8,
            color: "white",
            fontSize: 14,
            cursor: loading || !input.trim() ? "not-allowed" : "pointer",
            opacity: loading || !input.trim() ? 0.4 : 1,
            alignSelf: "stretch",
          }}
        >
          send
        </button>
      </div>
    </main>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div style={{ padding: "20px 0", opacity: 0.9 }}>
      <p style={{ fontSize: 14, opacity: 0.6, marginBottom: 16 }}>
        Try asking…
      </p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
        }}
      >
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            style={{
              textAlign: "left",
              padding: "12px 14px",
              background: "#15151a",
              border: "1px solid #2a2a30",
              borderRadius: 8,
              color: "#d0d0d0",
              fontSize: 13,
              cursor: "pointer",
              lineHeight: 1.4,
            }}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({ msg }: { msg: Msg }) {
  const [showTrace, setShowTrace] = useState(false);
  const isUser = msg.role === "user";

  return (
    <div
      style={{
        padding: "12px 16px",
        borderRadius: 10,
        background: isUser ? "#152841" : "#141416",
        border: `1px solid ${isUser ? "#1f3a5a" : "#23232a"}`,
      }}
    >
      <div
        style={{
          fontSize: 11,
          opacity: 0.5,
          marginBottom: 8,
          textTransform: "uppercase",
          letterSpacing: 0.4,
        }}
      >
        {isUser ? "you" : "assistant"}
      </div>

      {isUser ? (
        <div
          style={{
            whiteSpace: "pre-wrap",
            fontSize: 14,
            lineHeight: 1.5,
          }}
        >
          {msg.text}
        </div>
      ) : (
        <MarkdownBody text={msg.text} />
      )}

      {!isUser && msg.trace && msg.trace.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button
            onClick={() => setShowTrace(!showTrace)}
            style={{
              padding: "4px 8px",
              background: "transparent",
              border: "1px solid #2a2a30",
              borderRadius: 6,
              color: "#888",
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            {showTrace ? "▾" : "▸"} {msg.trace.length} tool call
            {msg.trace.length === 1 ? "" : "s"}
          </button>
          {showTrace && (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
              {msg.trace.map((t, i) => (
                <div
                  key={i}
                  style={{
                    padding: 10,
                    background: "#0e0e10",
                    border: "1px solid #1f1f22",
                    borderRadius: 6,
                    fontSize: 12,
                    fontFamily: "ui-monospace, SFMono-Regular, monospace",
                  }}
                >
                  <div style={{ color: "#7aa3d4", marginBottom: 4 }}>
                    {t.name}({JSON.stringify(t.args)})
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      color: "#aaa",
                      fontSize: 11,
                    }}
                  >
                    {JSON.stringify(t.result, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const markdownComponents = {
  p: (props: HTMLAttributes<HTMLParagraphElement>) => (
    <p style={{ margin: "0 0 10px", lineHeight: 1.55, fontSize: 14 }} {...props} />
  ),
  ul: (props: HTMLAttributes<HTMLUListElement>) => (
    <ul style={{ margin: "0 0 10px", paddingLeft: 22, fontSize: 14, lineHeight: 1.55 }} {...props} />
  ),
  ol: (props: HTMLAttributes<HTMLOListElement>) => (
    <ol style={{ margin: "0 0 10px", paddingLeft: 22, fontSize: 14, lineHeight: 1.55 }} {...props} />
  ),
  li: (props: HTMLAttributes<HTMLLIElement>) => (
    <li style={{ marginBottom: 3 }} {...props} />
  ),
  code: (props: HTMLAttributes<HTMLElement>) => (
    <code
      style={{
        background: "#0e0e10",
        padding: "1px 5px",
        borderRadius: 4,
        fontSize: "0.92em",
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
      }}
      {...props}
    />
  ),
  pre: (props: HTMLAttributes<HTMLPreElement>) => (
    <pre
      style={{
        background: "#0e0e10",
        padding: 10,
        borderRadius: 6,
        overflow: "auto",
        fontSize: 12,
        margin: "0 0 10px",
      }}
      {...props}
    />
  ),
  table: (props: HTMLAttributes<HTMLTableElement>) => (
    <div style={{ overflowX: "auto", margin: "0 0 10px" }}>
      <table
        style={{
          borderCollapse: "collapse",
          fontSize: 13,
          width: "100%",
        }}
        {...props}
      />
    </div>
  ),
  th: (props: HTMLAttributes<HTMLTableCellElement>) => (
    <th
      style={{
        textAlign: "left",
        padding: "6px 10px",
        borderBottom: "1px solid #2a2a30",
        background: "#1a1a1f",
      }}
      {...props}
    />
  ),
  td: (props: HTMLAttributes<HTMLTableCellElement>) => (
    <td
      style={{
        padding: "6px 10px",
        borderBottom: "1px solid #1a1a1f",
      }}
      {...props}
    />
  ),
  strong: (props: HTMLAttributes<HTMLElement>) => (
    <strong style={{ color: "#fff" }} {...props} />
  ),
  blockquote: (props: HTMLAttributes<HTMLQuoteElement>) => (
    <blockquote
      style={{
        borderLeft: "3px solid #2a5a8a",
        padding: "4px 12px",
        margin: "0 0 10px",
        opacity: 0.85,
        fontStyle: "italic",
      }}
      {...props}
    />
  ),
};

function MarkdownBody({ text }: { text: string }) {
  // useMemo so we don't re-parse markdown on every parent re-render
  return useMemo(
    () => (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    ),
    [text],
  );
}
