"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8300";
const ASSISTANT_NAME = process.env.NEXT_PUBLIC_ASSISTANT_NAME ?? "Ridoy AI";

type Citation = { document_id: string; title: string; score: number };
type ToolEvent = { name: string; phase: "call" | "result"; payload: unknown };

type UIMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  toolEvents?: ToolEvent[];
};

type ChatEvent =
  | { type: "citations"; citations: Citation[] }
  | { type: "delta"; content: string }
  | { type: "tool_call"; name: string; arguments: unknown }
  | { type: "tool_result"; name: string; result: unknown }
  | { type: "done" }
  | { type: "error"; message: string };

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/chat/sessions`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => setSessionId(data.session_id))
      .catch(() => setError(`Could not reach ${ASSISTANT_NAME}'s backend at ${API_BASE}.`));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || !sessionId || busy) return;

    setError(null);
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", content: text }, { role: "assistant", content: "" }]);

    function updateAssistant(patch: (msg: UIMessage) => UIMessage) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = patch(next[next.length - 1]);
        return next;
      });
    }

    try {
      const resp = await fetch(`${API_BASE}/api/chat/sessions/${sessionId}/messages/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!resp.ok || !resp.body) {
        throw new Error(`Backend returned ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, boundary).trim();
          buffer = buffer.slice(boundary + 2);
          if (!rawEvent.startsWith("data:")) continue;

          const evt = JSON.parse(rawEvent.slice(5).trim()) as ChatEvent;

          if (evt.type === "citations") {
            updateAssistant((m) => ({ ...m, citations: evt.citations }));
          } else if (evt.type === "delta") {
            updateAssistant((m) => ({ ...m, content: m.content + evt.content }));
          } else if (evt.type === "tool_call") {
            updateAssistant((m) => ({
              ...m,
              toolEvents: [...(m.toolEvents ?? []), { name: evt.name, phase: "call", payload: evt.arguments }],
            }));
          } else if (evt.type === "tool_result") {
            updateAssistant((m) => ({
              ...m,
              toolEvents: [...(m.toolEvents ?? []), { name: evt.name, phase: "result", payload: evt.result }],
            }));
          } else if (evt.type === "error") {
            setError(evt.message);
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong talking to the backend.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <div className="header">
        <h1>{ASSISTANT_NAME}</h1>
        <p>Self-hosted, open-weight assistant. Nothing here is sent to Anthropic, OpenAI, or Google.</p>
      </div>

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            {m.content || (m.role === "assistant" && busy && i === messages.length - 1 ? "…" : "")}
            {(m.citations?.length || m.toolEvents?.length) && (
              <div className="meta-row">
                {m.citations?.map((c) => (
                  <span key={c.document_id} className="badge" title={`similarity ${c.score}`}>
                    📄 {c.title}
                  </span>
                ))}
                {m.toolEvents
                  ?.filter((t) => t.phase === "call")
                  .map((t, idx) => (
                    <span key={idx} className="badge tool">
                      🔧 {t.name}
                    </span>
                  ))}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder={sessionId ? "Ask anything…" : "Connecting…"}
          disabled={!sessionId || busy}
        />
        <button onClick={sendMessage} disabled={!sessionId || busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
