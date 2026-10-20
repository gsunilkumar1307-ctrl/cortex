import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import {
  Mic, MicOff, Send, Square, Check, X,
  Search, Terminal, Globe, Folder, Settings,
  Zap, RefreshCw, ChevronRight, Eye, Compass,
  Volume2, VolumeX, Mail, Languages, FileEdit,
  Inbox, AtSign, Clock, AlertTriangle,
} from "lucide-react";
import "./styles.css";

const API = "http://127.0.0.1:8765";

// ─── IPC bridge (works in Electron; no-op in browser) ──────────────────────
const ipc = window.require ? window.require("electron").ipcRenderer : null;

// ─── Language metadata ───────────────────────────────────────────────────────
const LANG_META = {
  kn: { label: "ಕನ್ನಡ",  flag: "🇮🇳", name: "Kannada", bcp: "kn-IN" },
  hi: { label: "हिन्दी",  flag: "🇮🇳", name: "Hindi",   bcp: "hi-IN" },
  ta: { label: "தமிழ்",   flag: "🇮🇳", name: "Tamil",   bcp: "ta-IN" },
  te: { label: "తెలుగు",  flag: "🇮🇳", name: "Telugu",  bcp: "te-IN" },
  en: { label: "English", flag: "🌐", name: "English",  bcp: "en-US" },
};

// ─── Command Palette Items ──────────────────────────────────────────────────
const PALETTE_COMMANDS = [
  { id: "mail_summary", icon: Inbox,     label: "Summarize my emails",      hint: "Mail AI" },
  { id: "mail_draft",   icon: FileEdit,  label: "Draft an email",           hint: "Apple Mail" },
  { id: "vision",       icon: Eye,       label: "Look at my screen",        hint: "Screen vision" },
  { id: "browse",       icon: Compass,   label: "Open URL in browser",      hint: "Web automate" },
  { id: "search",       icon: Globe,     label: "Search the web",           hint: "Ask Cortex" },
  { id: "run",          icon: Terminal,  label: "Run terminal command",      hint: "Automate" },
  { id: "open",         icon: Folder,    label: "Open file or app",          hint: "Navigate" },
  { id: "automate",     icon: Zap,       label: "Automate a task",           hint: "Computer control" },
  { id: "refresh",      icon: RefreshCw, label: "Restart cloud brain",       hint: "⌘R" },
  { id: "settings",     icon: Settings,  label: "Settings",                  hint: "⌘," },
];

// ─── Utility ─────────────────────────────────────────────────────────────────
function statusToMode(status) {
  if (!status) return "idle";
  if (["waiting_approval"].includes(status)) return "waiting";
  if (["running", "executing"].includes(status)) return "thinking";
  return "idle";
}

// ─── Language Badge ──────────────────────────────────────────────────────────
function LanguageBadge({ lang }) {
  if (!lang || lang === "en" || lang === "auto") return null;
  const meta = LANG_META[lang];
  if (!meta) return null;
  return (
    <div className="lang-badge">
      <Languages size={11} />
      <span>{meta.flag} {meta.name}</span>
    </div>
  );
}

// ─── Rich Response Card ──────────────────────────────────────────────────────
function ResponseCard({ task, message }) {
  if (!task || !message) return <div className="response">{message || "…"}</div>;

  const cmd = task.command;
  const lang = task.language || "en";

  // ── Mail Read card ──
  if (cmd === "read_mail" && task.status === "completed") {
    const emails = task.auditTrail?.find(e => e.data?.emails)?.data?.emails || [];
    return (
      <div className="result-card mail-card">
        <div className="result-card-header">
          <div className="result-card-icon mail-icon"><Inbox size={16} /></div>
          <span className="result-card-title">Inbox</span>
          <LanguageBadge lang={lang} />
          <span className="result-card-count">{emails.length} messages</span>
        </div>
        {emails.length > 0 ? (
          <div className="mail-list">
            {emails.map((email, i) => (
              <div key={i} className="mail-item">
                <div className="mail-from">
                  <AtSign size={11} />
                  <span>{email.sender}</span>
                </div>
                <div className="mail-subject">{email.subject}</div>
                {email.snippet && <div className="mail-snippet">{email.snippet}</div>}
                <div className="mail-date"><Clock size={10} />{email.date}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mail-empty">✓ Your inbox is clear</div>
        )}
      </div>
    );
  }

  // ── Mail Summarize card ──
  if (cmd === "summarize_mail" && task.status === "completed") {
    return (
      <div className="result-card mail-card">
        <div className="result-card-header">
          <div className="result-card-icon mail-icon"><Mail size={16} /></div>
          <span className="result-card-title">Email Summary</span>
          <LanguageBadge lang={lang} />
        </div>
        <p className="result-card-body">{message}</p>
      </div>
    );
  }

  // ── Mail Draft card ──
  if (cmd === "draft_mail" && task.status === "completed") {
    const p = task.params || {};
    const toDisplay = p.recipient_email && p.recipient && p.recipient !== p.recipient_email
      ? `${p.recipient} <${p.recipient_email}>`
      : (p.recipient || p.recipient_email);
    const bodyContent = p.formatted_body || p.body;
    return (
      <div className="result-card draft-card">
        <div className="result-card-header">
          <div className="result-card-icon draft-icon"><FileEdit size={16} /></div>
          <span className="result-card-title">Draft Created</span>
          <LanguageBadge lang={lang} />
        </div>
        <div className="draft-fields">
          {toDisplay && <div className="draft-field"><span className="draft-label">To</span><span className="draft-value">{toDisplay}</span></div>}
          {p.sender_account && <div className="draft-field"><span className="draft-label">From</span><span className="draft-value">{p.sender_account}</span></div>}
          {p.subject   && <div className="draft-field"><span className="draft-label">Subject</span><span className="draft-value">{p.subject}</span></div>}
          {p.attachments && p.attachments.length > 0 && <div className="draft-field"><span className="draft-label">Attachments</span><span className="draft-value">{p.attachments.join(", ")}</span></div>}
          {bodyContent && <div className="draft-field draft-body-field"><span className="draft-label">Body</span><span className="draft-value" style={{ whiteSpace: "pre-wrap" }}>{bodyContent}</span></div>}
        </div>
        <div className="draft-status">✓ Mailbox opened with your draft</div>
      </div>
    );
  }

  // ── Mail Send approval card ──
  if (cmd === "send_mail" && task.status === "waiting_approval") {
    const p = task.params || {};
    const toDisplay = p.recipient_email && p.recipient && p.recipient !== p.recipient_email
      ? `${p.recipient} <${p.recipient_email}>`
      : (p.recipient || p.recipient_email);
    const bodyContent = p.formatted_body || p.body;
    return (
      <div className="result-card send-card">
        <div className="result-card-header">
          <AlertTriangle size={16} className="send-warn-icon" />
          <span className="result-card-title">Ready to Send Email</span>
          <LanguageBadge lang={lang} />
        </div>
        <div className="draft-fields">
          {toDisplay && <div className="draft-field"><span className="draft-label">To</span><span className="draft-value">{toDisplay}</span></div>}
          {p.sender_account && <div className="draft-field"><span className="draft-label">From</span><span className="draft-value">{p.sender_account}</span></div>}
          {p.subject   && <div className="draft-field"><span className="draft-label">Subject</span><span className="draft-value">{p.subject}</span></div>}
          {p.attachments && p.attachments.length > 0 && <div className="draft-field"><span className="draft-label">Attachments</span><span className="draft-value">{p.attachments.join(", ")}</span></div>}
          {bodyContent && <div className="draft-field draft-body-field"><span className="draft-label">Body</span><span className="draft-value" style={{ whiteSpace: "pre-wrap" }}>{bodyContent}</span></div>}
        </div>
        <div className="send-note">👆 Review the exact content above. Click Approve to send, or reply with edits.</div>
      </div>
    );
  }

  // ── Language-detected response ──
  const hasLangEvent = task.auditTrail?.some(e => e.type === "language_detected");
  if (hasLangEvent && lang !== "en" && cmd === "ask_question") {
    return (
      <div className="result-card lang-response-card">
        <div className="result-card-header">
          <Languages size={16} />
          <LanguageBadge lang={lang} />
        </div>
        <p className="result-card-body">{message}</p>
      </div>
    );
  }

  // ── Default: plain response with optional lang badge ──
  return (
    <div className="response">
      {hasLangEvent && <LanguageBadge lang={lang} />}
      <span>{message}</span>
    </div>
  );
}

// ─── Timeline Item ──────────────────────────────────────────────────────────
function TimelineItem({ event }) {
  const iconMap = { completed: "✓", failed: "✕", approved: "✓", rejected: "✕", started: "▶", created: "◉" };
  const classMap = { completed: "done", failed: "bad", approved: "done", rejected: "bad", started: "active", created: "active" };
  const cls = classMap[event.type] || "active";
  return (
    <div className="timeline-item">
      <div className={`timeline-icon ${cls}`}>{iconMap[event.type] || "·"}</div>
      <div className="timeline-content">
        <strong>{event.type.replace(/_/g, " ")}</strong>
        <span>{event.message}</span>
      </div>
    </div>
  );
}

// ─── Mail Draft Modal ─────────────────────────────────────────────────────────
function DraftModal({ onClose, onSend }) {
  const [to, setTo]       = useState("");
  const [subj, setSubj]   = useState("");
  const [body, setBody]   = useState("");

  function submit(action) {
    if (!to.trim()) return;
    const cmd = `${action === "send" ? "send" : "draft"} email to ${to} with subject ${subj || "Note from Cortex"} saying ${body || ""}`;
    onSend(cmd);
    onClose();
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="draft-modal" onClick={e => e.stopPropagation()}>
        <div className="draft-modal-header">
          <FileEdit size={16} />
          <span>Compose Email</span>
          <button className="draft-modal-close" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="draft-modal-fields">
          <div className="draft-modal-row">
            <label>To</label>
            <input value={to} onChange={e => setTo(e.target.value)} placeholder="recipient@email.com" autoFocus />
          </div>
          <div className="draft-modal-row">
            <label>Subject</label>
            <input value={subj} onChange={e => setSubj(e.target.value)} placeholder="Subject…" />
          </div>
          <div className="draft-modal-row body-row">
            <label>Body</label>
            <textarea value={body} onChange={e => setBody(e.target.value)} placeholder="Write your message…" rows={5} />
          </div>
        </div>
        <div className="draft-modal-actions">
          <button className="btn-draft-action draft" onClick={() => submit("draft")}>
            <FileEdit size={14} /> Save Draft
          </button>
          <button className="btn-draft-action send" onClick={() => submit("send")}>
            <Send size={14} /> Send (with approval)
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Command Palette ─────────────────────────────────────────────────────────
function CommandPalette({ onClose, onCommand, onDraftModal }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const filtered = PALETTE_COMMANDS.filter(c =>
    c.label.toLowerCase().includes(query.toLowerCase())
  );

  function handleKey(e) {
    if (e.key === "Escape") { onClose(); return; }
    if (e.key === "ArrowDown") { setSelected(s => Math.min(s + 1, filtered.length - 1)); return; }
    if (e.key === "ArrowUp")   { setSelected(s => Math.max(s - 1, 0)); return; }
    if (e.key === "Enter") {
      if (query.trim()) {
        onCommand(query.trim());
        onClose();
      } else if (filtered[selected]) {
        handleCommandClick(filtered[selected]);
      }
    }
  }

  function handleCommandClick(cmd) {
    if (cmd.id === "mail_draft") {
      onDraftModal();
      onClose();
      return;
    }
    onCommand(cmd.label);
    onClose();
  }

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <div className="palette-input-wrap">
          <Search size={18} />
          <input
            ref={inputRef}
            className="palette-input"
            placeholder="Ask Cortex anything, or pick a command…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKey}
          />
          <span className="palette-hint">ESC to close</span>
        </div>
        <div className="palette-section-label">Quick Actions</div>
        <div className="palette-items">
          {filtered.map((cmd, i) => (
            <div
              key={cmd.id}
              className={`palette-item ${i === selected ? "selected" : ""}`}
              onClick={() => handleCommandClick(cmd)}
            >
              <div className="palette-item-icon"><cmd.icon size={15} /></div>
              <span className="palette-item-label">{cmd.label}</span>
              <span className="palette-item-kbd">{cmd.hint}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── HUD Overlay ─────────────────────────────────────────────────────────────
function Hud({ task }) {
  if (!task || !["running", "executing"].includes(task.status)) return null;
  const steps = task.auditTrail || [];
  return (
    <div className="hud">
      <div className="hud-header">
        <div className="hud-dot" />
        <span className="hud-title">Cortex · Live</span>
      </div>
      {steps.length === 0 && <div className="hud-step">Initialising…</div>}
      {steps.map((s, i) => (
        <div key={`${s.createdAt}-${i}`} className={`hud-step ${i < steps.length - 1 ? "done" : ""}`}>
          {s.message}
        </div>
      ))}
      <div className="hud-step" style={{ color: "var(--muted)", fontSize: "11px", borderLeft: "none", paddingLeft: 0 }}>
        Intent: {task.intent}
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────
function App() {
  const [message, setMessage]         = useState("");
  const [task, setTask]               = useState(null);
  const [assistant, setAssistant]     = useState("Hey — I'm Cortex. What shall we do?");
  const [transcript, setTranscript]   = useState("");
  const [loading, setLoading]         = useState(false);
  const [listening, setListening]     = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [draftOpen, setDraftOpen]     = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [detectedLang, setDetectedLang] = useState("en");

  const recognitionRef      = useRef(null);
  const audioActiveRef      = useRef(false);
  const isSpeakingRef       = useRef(false);
  const isListeningRef      = useRef(false);
  const sendTimeoutRef      = useRef(null);
  const audioCtxRef          = useRef(null);
  const mediaStreamRef       = useRef(null);
  const processorRef         = useRef(null);
  const userAudioChunksRef   = useRef([]);
  const isRecordingUserRef   = useRef(false);
  const lastVoiceTimeRef     = useRef(0);

  // ── IPC: sync HUD ──
  useEffect(() => {
    if (!ipc || !task) return;
    if (["running", "executing"].includes(task.status)) {
      ipc.send("hud-show", { intent: task.intent, steps: task.auditTrail });
    } else {
      ipc.send("hud-hide");
    }
  }, [task]);

  // ── ⌘K shortcut ──
  useEffect(() => {
    function onToggle() { setPaletteOpen(p => !p); }
    if (ipc) {
      ipc.on("toggle-palette", onToggle);
      return () => ipc.removeListener("toggle-palette", onToggle);
    }
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); onToggle(); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // ─── Audio Chimes ───────────────────────────────────────────────────────────
  function playChime(type = "activate") {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      if (type === "activate") {
        [523.25, 659.25, 783.99].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now + idx * 0.07);
          gain.gain.setValueAtTime(0, now + idx * 0.07);
          gain.gain.linearRampToValueAtTime(0.12, now + idx * 0.07 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.07 + 0.26);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.07); osc.stop(now + idx * 0.07 + 0.28);
        });
      } else if (type === "deactivate") {
        [659.25, 523.25].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now + idx * 0.08);
          gain.gain.setValueAtTime(0, now + idx * 0.08);
          gain.gain.linearRampToValueAtTime(0.09, now + idx * 0.08 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.22);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.08); osc.stop(now + idx * 0.08 + 0.24);
        });
      } else if (type === "success") {
        [587.33, 880.00].forEach((freq) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now);
          gain.gain.setValueAtTime(0.09, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now); osc.stop(now + 0.38);
        });
      } else if (type === "alert") {
        [440, 554.37].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "triangle"; osc.frequency.setValueAtTime(freq, now + idx * 0.11);
          gain.gain.setValueAtTime(0.08, now + idx * 0.11);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.11 + 0.18);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.11); osc.stop(now + idx * 0.11 + 0.2);
        });
      }
    } catch {}
  }

  // ─── Audio helpers ──────────────────────────────────────────────────────────
  function downsampleBuffer(buffer, sampleRate, outSampleRate = 16000) {
    if (outSampleRate === sampleRate) return buffer;
    const ratio = sampleRate / outSampleRate;
    const newLen = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLen);
    let rOff = 0, bOff = 0;
    while (rOff < result.length) {
      const nextBOff = Math.round((rOff + 1) * ratio);
      let accum = 0, count = 0;
      for (let i = bOff; i < nextBOff && i < buffer.length; i++) { accum += buffer[i]; count++; }
      result[rOff] = count ? accum / count : buffer[bOff];
      rOff++; bOff = nextBOff;
    }
    return result;
  }

  function encodeWAV(samples, sampleRate = 16000) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buf);
    const ws = (v, off, str) => { for (let i = 0; i < str.length; i++) v.setUint8(off + i, str.charCodeAt(i)); };
    ws(view, 0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true);
    ws(view, 8, "WAVE"); ws(view, 12, "fmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    ws(view, 36, "data"); view.setUint32(40, samples.length * 2, true);
    let off = 44;
    for (let i = 0; i < samples.length; i++, off += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  // ─── speakText: multilingual TTS ────────────────────────────────────────────
  function speakText(text, langCode = "en", onDone) {
    if (!("speechSynthesis" in window)) { if (onDone) onDone(); return; }
    try {
      window.speechSynthesis.cancel();
      isSpeakingRef.current = true;

      let speech = text
        .replace(/```[\s\S]*?```/g, "")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/https?:\/\/\S+/g, "")
        .replace(/[*_#~>[\]()]/g, "")
        .replace(/^\s*[-•*]\s+/gm, "")
        .replace(/^\s*\d+\.\s+/gm, "")
        .replace(/\s+/g, " ")
        .trim();

      if (!speech) { isSpeakingRef.current = false; if (onDone) onDone(); return; }

      const utterance = new SpeechSynthesisUtterance(speech);
      utterance.rate = 0.97;
      utterance.pitch = 1.03;

      // ── Language-aware voice selection ──────────────────────────────────────
      const targetBcp = LANG_META[langCode]?.bcp || "en-US";
      const voices = window.speechSynthesis.getVoices();

      let chosen = null;

      if (langCode !== "en") {
        // Try exact language match first (e.g. "kn-IN", "hi-IN")
        chosen =
          voices.find(v => v.lang === targetBcp && (v.name.includes("Enhanced") || v.name.includes("Premium"))) ||
          voices.find(v => v.lang === targetBcp) ||
          voices.find(v => v.lang.startsWith(langCode));
      }

      if (!chosen) {
        // Fallback to best English voice
        chosen =
          voices.find(v => v.lang.startsWith("en") && (v.name.includes("Enhanced") || v.name.includes("Premium") || v.name.includes("Natural"))) ||
          voices.find(v => v.lang.startsWith("en") && (v.name.includes("Samantha") || v.name.includes("Ava") || v.name.includes("Daniel") || v.name.includes("Karen") || v.name.includes("Serena"))) ||
          voices.find(v => v.lang.startsWith("en") && v.name.includes("Google")) ||
          voices.find(v => v.lang.startsWith("en"));
      }

      if (chosen) {
        utterance.voice = chosen;
        utterance.lang  = chosen.lang;
      }

      let finished = false;
      const handleEnd = () => {
        if (finished) return;
        finished = true;
        isSpeakingRef.current = false;
        if (window._speechSafetyTimeout) clearTimeout(window._speechSafetyTimeout);
        if (onDone) onDone();
      };
      utterance.onend = handleEnd;
      utterance.onerror = handleEnd;
      window._cortexUtterance = utterance;
      const maxDur = Math.max(3000, speech.length * 110);
      window._speechSafetyTimeout = setTimeout(handleEnd, maxDur);
      window.speechSynthesis.speak(utterance);
    } catch {
      isSpeakingRef.current = false;
      if (onDone) onDone();
    }
  }

  // ── Send text to brain ──────────────────────────────────────────────────────
  const sendMessage = useCallback(async (source = "text", override = "") => {
    const text = (override || message).trim();
    if (!text) return;
    setLoading(true);
    setTranscript(text);
    setMessage("");
    setAssistant("…");
    try {
      const res  = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, source }),
      });
      const data = await res.json();
      const lang = data.task?.language || "en";
      setDetectedLang(lang);
      setAssistant(data.message);
      setTask(data.task || null);

      if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
        playChime("alert");
      } else if (data.task?.status === "completed") {
        playChime("success");
      }

      speakText(data.message, lang, () => {
        setAssistant(prev => prev === data.message ? "Listening — speak anytime…" : prev);
      });
    } catch {
      const errMsg = "Could not reach Cortex. Is the server running?";
      setAssistant(`⚠ ${errMsg}`);
      speakText(errMsg, "en");
    } finally {
      setLoading(false);
    }
  }, [message]);

  // ── Stop Audio ──────────────────────────────────────────────────────────────
  const stopAudioPipeline = useCallback(() => {
    isListeningRef.current = false;
    isRecordingUserRef.current = false;
    setListening(false);
    if (processorRef.current) { try { processorRef.current.disconnect(); } catch {} processorRef.current = null; }
    if (audioCtxRef.current)  { try { audioCtxRef.current.close(); } catch {} audioCtxRef.current = null; }
    if (mediaStreamRef.current) { try { mediaStreamRef.current.getTracks().forEach(t => t.stop()); } catch {} mediaStreamRef.current = null; }
  }, []);

  // ── Send WAV to /audio_chat ─────────────────────────────────────────────────
  const sendAudioChunk = useCallback(async (chunks, sampleRate) => {
    if (!chunks || chunks.length === 0) return;
    let totalLen = 0;
    for (const c of chunks) totalLen += c.length;
    if (totalLen < 6000) return;

    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const c of chunks) { merged.set(c, offset); offset += c.length; }

    const wavBlob = encodeWAV(downsampleBuffer(merged, sampleRate, 16000), 16000);

    setLoading(true);
    setAssistant("Thinking…");
    try {
      const res = await fetch(`${API}/audio_chat`, {
        method: "POST", headers: { "Content-Type": "audio/wav" }, body: wavBlob,
      });
      const data = await res.json();
      const lang = data.task?.language || "en";
      setDetectedLang(lang);
      if (data.transcript) setTranscript(data.transcript);
      setAssistant(data.message);
      setTask(data.task || null);

      if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
        playChime("alert");
      } else if (data.task?.status === "completed") {
        playChime("success");
      }

      speakText(data.message, lang, () => {
        setAssistant(prev => prev === data.message ? "Listening — talk naturally…" : prev);
      });
    } catch (err) {
      console.warn("Audio chat request failed:", err);
      setAssistant("Could not connect to Cortex brain.");
    } finally {
      setLoading(false);
    }
  }, []);

  // ── Start Audio Pipeline (VAD) ──────────────────────────────────────────────
  const startAudioPipeline = useCallback(async () => {
    if (!audioActiveRef.current) return;
    stopAudioPipeline();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      mediaStreamRef.current = stream;
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (!audioActiveRef.current || isSpeakingRef.current) return;
        const inputData = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
        const rms = Math.sqrt(sum / inputData.length);

        if (rms > 0.016) {
          if (!isRecordingUserRef.current) {
            isRecordingUserRef.current = true;
            userAudioChunksRef.current = [];
            setListening(true);
            setAssistant("Listening…");
          }
          userAudioChunksRef.current.push(new Float32Array(inputData));
          lastVoiceTimeRef.current = Date.now();
        } else if (isRecordingUserRef.current) {
          userAudioChunksRef.current.push(new Float32Array(inputData));
          if (Date.now() - lastVoiceTimeRef.current > 750) {
            isRecordingUserRef.current = false;
            setListening(false);
            const recorded = [...userAudioChunksRef.current];
            userAudioChunksRef.current = [];
            sendAudioChunk(recorded, ctx.sampleRate);
          }
        }
      };

      source.connect(processor);
      const silentGain = ctx.createGain();
      silentGain.gain.value = 0;
      processor.connect(silentGain);
      silentGain.connect(ctx.destination);
      isListeningRef.current = true;
      setAssistant("Listening — talk naturally…");
    } catch (err) {
      console.warn("Microphone access failed:", err);
      audioActiveRef.current = false;
      setAudioEnabled(false);
      setAssistant("Microphone access is blocked in macOS. Please enable it in System Settings.");
    }
  }, [stopAudioPipeline, sendAudioChunk]);

  // ── Audio toggle ────────────────────────────────────────────────────────────
  async function toggleAudio() {
    if (audioEnabled) {
      playChime("deactivate");
      audioActiveRef.current = false;
      setAudioEnabled(false);
      stopAudioPipeline();
      try { window.speechSynthesis?.cancel(); } catch {}
      setAssistant("Audio & voice deactivated.");
    } else {
      playChime("activate");
      audioActiveRef.current = true;
      setAudioEnabled(true);
      setAssistant("Audio activated. I'm listening…");
      speakText("Audio enabled. I'm listening.", "en", () => { startAudioPipeline(); });
    }
  }

  // ── Approval / Cancel ───────────────────────────────────────────────────────
  async function decide(approved) {
    if (!task) return;
    approved ? playChime("success") : playChime("deactivate");
    const res = await fetch(`${API}/tasks/${task.id}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
    const data = await res.json();
    setTask(data);
    const lang = data.language || detectedLang || "en";
    speakText(approved ? "Approved. Executing task." : "Rejected.", lang, () => {
      setAssistant("Listening — speak anytime…");
    });
  }

  async function cancel() {
    playChime("deactivate");
    stopAudioPipeline();
    try { window.speechSynthesis?.cancel(); } catch {}
    if (!task) return;
    const res = await fetch(`${API}/tasks/${task.id}/cancel`, { method: "POST" });
    setTask(await res.json());
  }

  // ── Palette command dispatch ────────────────────────────────────────────────
  function handlePaletteCommand(cmd) {
    setMessage(cmd);
    sendMessage("text", cmd);
  }

  const orbState = listening ? "listening" : loading ? "thinking" : "";
  const terminal = ["completed", "failed", "blocked", "canceled"].includes(task?.status || "");
  const currentLang = task?.language || detectedLang || "en";

  return (
    <div className="app">
      {/* Title Bar */}
      <div className="titlebar">
        <span className="titlebar-label">Cortex</span>
        <div className="titlebar-status">
          {currentLang !== "en" && (
            <div className="titlebar-lang">
              <Languages size={12} />
              <span>{LANG_META[currentLang]?.name || currentLang}</span>
            </div>
          )}
          <div className={`status-dot ${loading ? "active" : task?.status === "waiting_approval" ? "warn" : task?.status === "failed" ? "bad" : ""}`} />
          <span className="status-text">{task ? task.status.replace(/_/g, " ") : "Ready"}</span>
        </div>
      </div>

      {/* Main Shell */}
      <div className="shell">
        <div className="stage">

          {/* Voice Orb */}
          <div className={`orb-wrap ${orbState}`}>
            <div className="orb-ring orb-ring-3" />
            <div className="orb-ring orb-ring-2" />
            <div className="orb-ring orb-ring-1" />
            <button
              className="voiceButton"
              onClick={() => audioEnabled ? (listening ? stopAudioPipeline() : startAudioPipeline()) : toggleAudio()}
              title={audioEnabled ? (listening ? "Mute mic" : "Tap to speak") : "Click to enable audio"}
              aria-label="Voice Orb"
            >
              {listening ? <MicOff size={34} /> : <Mic size={34} />}
            </button>
          </div>

          {/* Waveform */}
          <div className="waveform" aria-hidden="true">
            {Array.from({ length: 28 }).map((_, i) => (
              <span key={i} style={{ "--i": i + 1 }} />
            ))}
          </div>

          {/* Transcript + Rich Response */}
          <div className="chat-area">
            <div className="transcript">{transcript || "Listening — just speak or type below."}</div>
            <ResponseCard task={task} message={assistant} />
          </div>

          {/* Execution Timeline */}
          {task && task.auditTrail?.length > 0 && (
            <div className="timeline">
              {task.auditTrail.map((event, i) => (
                <TimelineItem key={`${event.createdAt}-${i}`} event={event} />
              ))}
            </div>
          )}

          {/* Approval Card */}
          {task?.requiresApproval && task.status === "waiting_approval" && (
            <div className="approval-card">
              <div className="approval-label">⚠ Action requires your approval</div>
              <div className="approval-desc">
                Cortex wants to: <strong>{task.command?.replace(/_/g, " ")}</strong>
                {task.params?.recipient && <> → <em>{task.params.recipient}</em></>}
                <br />Review the details above and approve or reject.
              </div>
              <div className="approval-actions">
                <button className="btn-approve" onClick={() => decide(true)}>
                  <Check size={15} /> Approve
                </button>
                <button className="btn-reject" onClick={() => decide(false)}>
                  <X size={15} /> Reject
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Dock */}
        <div className="dock">
          <button
            className={`audio-enable-btn ${audioEnabled ? "active" : ""}`}
            onClick={toggleAudio}
            title={audioEnabled ? "Click to turn off audio & mic" : "Click to enable voice & audio"}
          >
            <span className="audio-dot" />
            {audioEnabled
              ? (listening ? <><Mic size={14} /> Listening…</> : <><Volume2 size={14} /> Audio On</>)
              : <><VolumeX size={14} /> Enable Audio & Voice</>
            }
          </button>

          <div className="composer">
            <input
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => e.key === "Enter" && sendMessage()}
              placeholder="Type a command… or just speak  (⌘K for quick actions)"
            />
            <button className="iconButton primary" onClick={() => sendMessage()} disabled={loading} title="Send">
              <Send size={16} />
            </button>
            <button
              className={`iconButton ${listening ? "primary" : ""}`}
              onClick={() => audioEnabled ? (listening ? stopAudioPipeline() : startAudioPipeline()) : toggleAudio()}
              title={audioEnabled ? (listening ? "Mute mic" : "Tap to speak") : "Enable audio first"}
            >
              {listening ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
            <button className="iconButton" onClick={() => setDraftOpen(true)} title="Compose email">
              <Mail size={15} />
            </button>
            <button className="iconButton" onClick={cancel} disabled={!task || terminal} title="Stop task">
              <Square size={15} />
            </button>
          </div>
        </div>
      </div>

      {/* Command Palette */}
      {paletteOpen && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onCommand={handlePaletteCommand}
          onDraftModal={() => setDraftOpen(true)}
        />
      )}

      {/* Draft Modal */}
      {draftOpen && (
        <DraftModal
          onClose={() => setDraftOpen(false)}
          onSend={(cmd) => sendMessage("text", cmd)}
        />
      )}

      {/* HUD Overlay */}
      <Hud task={task} />
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
