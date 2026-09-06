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

function speak(text: string) {
  if (typeof window === "undefined" || !("speechSynthesis" in window) || !text.trim()) return;
  // Self-hosted end to end except this: SpeechSynthesis runs locally in the
  // browser/OS, not a network call to a third party -- consistent with
  // this assistant's "nothing leaves your infrastructure" promise, just
  // with noticeably more robotic voice quality than a cloud TTS API.
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/chat/sessions`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => setSessionId(data.session_id))
      .catch(() => setError(`Could not reach ${ASSISTANT_NAME}'s backend at ${API_BASE}.`));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
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

    let fullAssistantText = "";

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
            if (speakReplies) speak(fullAssistantText);
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

  async function toggleRecording() {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
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
      const resp = await fetch(`${API_BASE}/api/speech/transcribe`, { method: "POST", body: formData });
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

  return (
    <div className="app">
      <div className="header">
        <h1>{ASSISTANT_NAME}</h1>
        <p>Self-hosted, open-weight assistant. Nothing here is sent to Anthropic, OpenAI, or Google.</p>
        <label className="speak-toggle">
          <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} />
          🔊 Speak replies
        </label>
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
        <button
          onClick={toggleRecording}
          disabled={!sessionId || busy || transcribing}
          className={`mic-button ${recording ? "recording" : ""}`}
          title={recording ? "Stop recording" : "Record a voice message"}
        >
          {recording ? "⏹" : "🎤"}
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder={transcribing ? "Transcribing…" : sessionId ? "Ask anything…" : "Connecting…"}
          disabled={!sessionId || busy || recording || transcribing}
        />
        <button onClick={() => sendMessage()} disabled={!sessionId || busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
