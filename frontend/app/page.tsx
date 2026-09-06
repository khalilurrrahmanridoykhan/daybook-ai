"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8300";
const ASSISTANT_NAME = process.env.NEXT_PUBLIC_ASSISTANT_NAME ?? "DayBook AI";

const EXAMPLE_PROMPTS = ["What can you do?", "Tell me about Ridoy's projects", "What is 384 times 27?"];

type Citation = { document_id: string; title: string; score: number };
type ToolEvent = { name: string; phase: "call" | "result"; payload: unknown };

type UIMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  toolEvents?: ToolEvent[];
  elapsedMs?: number;
};

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
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const barRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/chat/sessions`, { method: "POST", credentials: "include" })
      .then((r) => {
        // Fallback for the two-port tunnel setup, where middleware.ts can't
        // see a cookie scoped to the backend's separate origin.
        if (r.status === 401) {
          window.location.href = "/login";
          throw new Error("not logged in");
        }
        return r.json();
      })
      .then((data) => setSessionId(data.session_id))
      .catch(() => setError(`Could not reach ${ASSISTANT_NAME}'s backend at ${API_BASE}.`));
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
    <div className="app">
      <div className="header">
        <div className="header-top">
          <h1>{ASSISTANT_NAME}</h1>
          <span className={`status-dot ${connectionState}`} title={connectionState} />
          <button
            type="button"
            className="logout-link"
            onClick={() => {
              fetch(`${API_BASE}/api/auth/logout`, { method: "POST", credentials: "include" }).finally(() => {
                window.location.href = "/login";
              });
            }}
          >
            Log out
          </button>
        </div>
        <p>Self-hosted, open-weight assistant. Nothing here is sent to Anthropic, OpenAI, or Google.</p>
        <label className="speak-toggle">
          <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} />
          🔊 Speak replies
        </label>
      </div>

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">🤖</div>
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
              <div className={`avatar ${m.role}`}>{m.role === "user" ? "🧑" : "🤖"}</div>
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
                    {m.elapsedMs != null && (
                      <span className="badge time" title="response time">
                        ⏱ {formatDuration(m.elapsedMs)}
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
          <span>Recording… {recordingSeconds}s (tap 🎤 to stop)</span>
        </div>
      )}

      <div className="composer">
        <button
          onClick={toggleRecording}
          disabled={!sessionId || busy || transcribing}
          className={`mic-button ${recording ? "recording" : ""} ${transcribing ? "transcribing" : ""}`}
          title={recording ? "Stop recording" : "Record a voice message"}
        >
          {transcribing ? <span className="spinner" /> : recording ? "⏹" : "🎤"}
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
  );
}
