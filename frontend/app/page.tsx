"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Clock,
  FileText,
  Loader2,
  Menu,
  Mic,
  MoreVertical,
  Pencil,
  Plus,
  Square,
  Trash2,
  User,
  Volume2,
  Wrench,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8300";
const ASSISTANT_NAME = process.env.NEXT_PUBLIC_ASSISTANT_NAME ?? "DayBook AI";

const EXAMPLE_PROMPTS = ["What can you do?", "What's on my task list today?", "Tell me about my budget"];
const SESSION_STORAGE_KEY = "daybook_ai_session_id";

type Citation = { document_id: string; title: string; score: number };
type ToolEvent = { name: string; phase: "call" | "result"; payload: unknown };

type UIMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  toolEvents?: ToolEvent[];
  elapsedMs?: number;
};

type SessionSummary = { id: string; title: string; created_at: string };

type ChatEvent =
  | { type: "citations"; citations: Citation[] }
  | { type: "delta"; content: string }
  | { type: "tool_call"; name: string; arguments: unknown }
  | { type: "tool_result"; name: string; result: unknown }
  | { type: "done" }
  | { type: "error"; message: string };

function speak(text: string) {
  if (typeof window === "undefined" || !("speechSynthesis" in window) || !text.trim()) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

function formatDuration(ms: number): string {
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const barRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Source of truth for "what chats exist" is always this list from the
  // backend, never localStorage alone -- localStorage only remembers
  // *which* one was last open, so a reload can never land on a genuinely
  // empty view as long as any session exists server-side.
  async function refreshSessions(): Promise<SessionSummary[] | null> {
    const resp = await fetch(`${API_BASE}/api/chat/sessions`, { credentials: "include" });
    if (resp.status === 401) {
      window.location.href = "/login";
      return null;
    }
    const list: SessionSummary[] = resp.ok ? await resp.json() : [];
    setSessions(list);
    return list;
  }

  async function loadSession(id: string) {
    const historyResp = await fetch(`${API_BASE}/api/chat/sessions/${id}/messages`, { credentials: "include" });
    if (historyResp.status === 401) {
      window.location.href = "/login";
      return;
    }
    const history: { role: "user" | "assistant"; content: string }[] = historyResp.ok ? await historyResp.json() : [];
    setMessages(history.map((m) => ({ role: m.role, content: m.content })));
    setSessionId(id);
    localStorage.setItem(SESSION_STORAGE_KEY, id);
    setMenuOpenId(null);
    setSidebarOpen(false);
  }

  async function startNewChat() {
    const resp = await fetch(`${API_BASE}/api/chat/sessions`, { method: "POST", credentials: "include" });
    if (resp.status === 401) {
      window.location.href = "/login";
      return;
    }
    const data = await resp.json();
    await refreshSessions();
    setMessages([]);
    setSessionId(data.session_id);
    localStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
    setMenuOpenId(null);
    setSidebarOpen(false);
  }

  async function deleteSession(id: string) {
    setMenuOpenId(null);

    const resp = await fetch(`${API_BASE}/api/chat/sessions/${id}`, { method: "DELETE", credentials: "include" });
    if (resp.status === 401) {
      window.location.href = "/login";
      return;
    }

    const remaining = sessions.filter((s) => s.id !== id);
    setSessions(remaining);

    if (id === sessionId) {
      if (remaining.length > 0) {
        await loadSession(remaining[0].id);
      } else {
        await startNewChat();
      }
    }
  }

  function startRename(session: SessionSummary) {
    setMenuOpenId(null);
    setEditingId(session.id);
    setEditingTitle(session.title);
  }

  async function commitRename(id: string) {
    const title = editingTitle.trim();
    setEditingId(null);
    if (!title) return;

    const current = sessions.find((s) => s.id === id);
    if (current && current.title === title) return;

    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
    const resp = await fetch(`${API_BASE}/api/chat/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ title }),
    });
    if (resp.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!resp.ok) {
      // Roll back on failure rather than leave the sidebar showing a title
      // that was never actually saved.
      refreshSessions();
    }
  }

  useEffect(() => {
    if (editingId) renameInputRef.current?.select();
  }, [editingId]);

  // Close any open 3-dot menu on an outside click.
  useEffect(() => {
    if (!menuOpenId) return;
    function onDocClick(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest(".session-menu")) setMenuOpenId(null);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpenId]);

  useEffect(() => {
    async function init() {
      const list = await refreshSessions();
      if (list === null) return; // redirected to /login

      const savedId = localStorage.getItem(SESSION_STORAGE_KEY);
      const target = list.find((s) => s.id === savedId) ?? list[0];

      if (target) {
        await loadSession(target.id);
      } else {
        await startNewChat();
      }
    }

    init().catch(() => setError(`Could not reach ${ASSISTANT_NAME}'s backend at ${API_BASE}.`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    return () => {
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || !sessionId || busy) return;

    const isFirstMessage = messages.length === 0;

    setError(null);
    setInput("");
    setBusy(true);
    setElapsedMs(0);
    setMessages((prev) => [...prev, { role: "user", content: text }, { role: "assistant", content: "" }]);

    const startedAt = performance.now();
    elapsedTimerRef.current = setInterval(() => setElapsedMs(performance.now() - startedAt), 100);

    function updateAssistant(patch: (msg: UIMessage) => UIMessage) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = patch(next[next.length - 1]);
        return next;
      });
    }

    let fullAssistantText = "";

    try {
      const resp = await fetch(`${API_BASE}/api/chat/sessions/${sessionId}/messages/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
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
            fullAssistantText += evt.content;
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
          } else if (evt.type === "done") {
            const finalMs = performance.now() - startedAt;
            updateAssistant((m) => ({ ...m, elapsedMs: finalMs }));
            if (speakReplies) speak(fullAssistantText);
            // The backend auto-titles a session from its first user
            // message -- pick that up in the sidebar without a reload.
            if (isFirstMessage) refreshSessions();
          } else if (evt.type === "error") {
            setError(evt.message);
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong talking to the backend.");
    } finally {
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
      setBusy(false);
    }
  }

  function startLevelMeter(stream: MediaStream) {
    const audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    audioCtxRef.current = audioCtx;
    analyserRef.current = analyser;

    const data = new Uint8Array(analyser.frequencyBinCount);
    const bands = 5;
    const bandSize = Math.floor(data.length / bands);

    function tick() {
      analyser.getByteFrequencyData(data);
      for (let i = 0; i < bands; i++) {
        let sum = 0;
        for (let j = i * bandSize; j < (i + 1) * bandSize; j++) sum += data[j];
        const level = Math.min(1, sum / bandSize / 180); // normalized, headroom above typical speech levels
        const bar = barRefs.current[i];
        if (bar) bar.style.transform = `scaleY(${0.15 + level * 0.85})`;
      }
      rafRef.current = requestAnimationFrame(tick);
    }
    tick();
  }

  function stopLevelMeter() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    analyserRef.current = null;
  }

  async function toggleRecording() {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      stopLevelMeter();
      return;
    }

    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await transcribeAndSend(blob);
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setRecordingSeconds(0);
      recordingTimerRef.current = setInterval(() => setRecordingSeconds((s) => s + 1), 1000);
      startLevelMeter(stream);
    } catch {
      setError("Couldn't access your microphone -- check your browser's permission for this page.");
    }
  }

  async function transcribeAndSend(blob: Blob) {
    setTranscribing(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", blob, "clip.webm");
      const resp = await fetch(`${API_BASE}/api/speech/transcribe`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail ?? `Transcription failed (${resp.status})`);
      }
      const { text } = (await resp.json()) as { text: string };
      if (text.trim()) {
        await sendMessage(text);
      } else {
        setError("Didn't catch any speech in that recording -- try again.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Transcription failed.");
    } finally {
      setTranscribing(false);
    }
  }

  const connectionState = error && !sessionId ? "offline" : sessionId ? "online" : "connecting";

  return (
    <div className={`layout ${sidebarOpen ? "sidebar-open" : ""}`}>
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}

      <aside className="sidebar">
        <button type="button" className="new-chat-button" onClick={startNewChat}>
          <Plus size={16} /> New chat
        </button>

        <div className="session-list">
          {sessions.map((s) => (
            <div key={s.id} className={`session-item ${s.id === sessionId ? "active" : ""}`}>
              {editingId === s.id ? (
                <input
                  ref={renameInputRef}
                  className="session-rename-input"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={() => commitRename(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <button type="button" className="session-title" onClick={() => loadSession(s.id)}>
                  {s.title || "New chat"}
                </button>
              )}

              <div className="session-menu">
                <button
                  type="button"
                  className="menu-trigger"
                  onClick={() => setMenuOpenId(menuOpenId === s.id ? null : s.id)}
                  title="Chat options"
                >
                  <MoreVertical size={16} />
                </button>
                {menuOpenId === s.id && (
                  <div className="menu-dropdown">
                    <button type="button" onClick={() => startRename(s)}>
                      <Pencil size={14} /> Rename
                    </button>
                    <button type="button" className="danger" onClick={() => deleteSession(s.id)}>
                      <Trash2 size={14} /> Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="app">
        <div className="header">
          <div className="header-top">
            <button
              type="button"
              className="sidebar-toggle"
              onClick={() => setSidebarOpen((v) => !v)}
              title="Chat history"
            >
              <Menu size={20} />
            </button>
            <h1>{ASSISTANT_NAME}</h1>
            <span className={`status-dot ${connectionState}`} title={connectionState} />
            <div className="header-actions">
              <button
                type="button"
                className="logout-link"
                onClick={() => {
                  fetch(`${API_BASE}/api/auth/logout`, { method: "POST", credentials: "include" }).finally(() => {
                    localStorage.removeItem(SESSION_STORAGE_KEY);
                    window.location.href = "/login";
                  });
                }}
              >
                Log out
              </button>
            </div>
          </div>
          <p>This is Ridoy Khan&rsquo;s Personal AI Assistant.</p>
          <label className="speak-toggle">
            <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} />
            <Volume2 size={14} /> Speak replies
          </label>
        </div>

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-icon">
                <Bot size={44} />
              </div>
              <p>Ask me anything, or try one of these:</p>
              <div className="prompt-chips">
                {EXAMPLE_PROMPTS.map((p) => (
                  <button key={p} className="prompt-chip" onClick={() => sendMessage(p)} disabled={!sessionId}>
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => {
            const isLive = m.role === "assistant" && busy && i === messages.length - 1;
            const isEmptyLive = isLive && !m.content;
            return (
              <div key={i} className={`message-row ${m.role}`}>
                <div className={`avatar ${m.role}`}>{m.role === "user" ? <User size={14} /> : <Bot size={14} />}</div>
                <div className={`message ${m.role}`}>
                  {isEmptyLive ? (
                    <div className="typing-indicator">
                      <span className="dot" />
                      <span className="dot" />
                      <span className="dot" />
                      <span className="thinking-label">Thinking… {formatDuration(elapsedMs)}</span>
                    </div>
                  ) : (
                    <>
                      {m.content}
                      {isLive && <span className="live-timer">{formatDuration(elapsedMs)}</span>}
                    </>
                  )}
                  {(m.citations?.length || m.toolEvents?.length || m.elapsedMs) && (
                    <div className="meta-row">
                      {m.citations?.map((c) => (
                        <span key={c.document_id} className="badge" title={`similarity ${c.score}`}>
                          <FileText size={12} /> {c.title}
                        </span>
                      ))}
                      {m.toolEvents
                        ?.filter((t) => t.phase === "call")
                        .map((t, idx) => (
                          <span key={idx} className="badge tool">
                            <Wrench size={12} /> {t.name}
                          </span>
                        ))}
                      {m.elapsedMs != null && (
                        <span className="badge time" title="response time">
                          <Clock size={12} /> {formatDuration(m.elapsedMs)}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {error && <div className="error-banner">{error}</div>}

        {recording && (
          <div className="recording-bar">
            <div className="level-meter">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="level-bar" ref={(el) => { barRefs.current[i] = el; }} />
              ))}
            </div>
            <span>
              Recording… {recordingSeconds}s (tap <Mic size={13} /> to stop)
            </span>
          </div>
        )}

        <div className="composer">
          <button
            onClick={toggleRecording}
            disabled={!sessionId || busy || transcribing}
            className={`mic-button ${recording ? "recording" : ""} ${transcribing ? "transcribing" : ""}`}
            title={recording ? "Stop recording" : "Record a voice message"}
          >
            {transcribing ? <Loader2 size={18} className="spin-icon" /> : recording ? <Square size={16} /> : <Mic size={18} />}
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder={transcribing ? "Transcribing…" : sessionId ? "Ask anything…" : "Connecting…"}
            disabled={!sessionId || busy || recording || transcribing}
          />
          <button className="send-button" onClick={() => sendMessage()} disabled={!sessionId || busy || !input.trim()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
