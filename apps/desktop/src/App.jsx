import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import {
  Mic, MicOff, Send, Check, X,
  Search, Terminal, Globe, Folder, Settings,
  Zap, RefreshCw, ChevronRight, Eye, Compass,
  Volume2, VolumeX, Mail, Languages, FileEdit,
  Inbox, AtSign, Clock, AlertTriangle, Radio, Sparkles,
  Sun, Moon, Trash2, Copy, Shield, Sliders, History, Play, Pin
} from "lucide-react";
import "./styles.css";

const API = "http://127.0.0.1:8765";

// ─── IPC bridge (works in Electron; safely no-op in browser) ──────────────────
const ipc = typeof window !== "undefined" && window.require ? window.require("electron").ipcRenderer : null;

// ─── Language metadata ────────────────────────────────────────────────────────
const LANG_META = {
  kn: { label: "ಕನ್ನಡ",  flag: "🇮🇳", name: "Kannada", bcp: "kn-IN" },
  hi: { label: "हिन्दी",  flag: "🇮🇳", name: "Hindi",   bcp: "hi-IN" },
  ta: { label: "தமிழ்",   flag: "🇮🇳", name: "Tamil",   bcp: "ta-IN" },
  te: { label: "తెలుగు",  flag: "🇮🇳", name: "Telugu",  bcp: "te-IN" },
  en: { label: "English", flag: "🌐", name: "English",  bcp: "en-US" },
};

// ─── Command Palette Items ───────────────────────────────────────────────────
const PALETTE_COMMANDS = [
  { id: "mail_summary", icon: Inbox,     label: "Summarize my emails",      hint: "Mail AI" },
  { id: "mail_draft",   icon: FileEdit,  label: "Draft an email",           hint: "Apple Mail" },
  { id: "settings",     icon: Settings,  label: "Open Settings",            hint: "⌘," },
  { id: "clear_history",icon: History,   label: "Clear Conversation History",hint: "New Session" },
  { id: "vision",       icon: Eye,       label: "Look at my screen",        hint: "Screen vision" },
  { id: "browse",       icon: Compass,   label: "Open URL in browser",      hint: "Web automate" },
  { id: "search",       icon: Globe,     label: "Search the web",           hint: "Ask Cortex" },
  { id: "run",          icon: Terminal,  label: "Run terminal command",     hint: "Automate" },
  { id: "open",         icon: Folder,    label: "Open file or app",         hint: "Navigate" },
  { id: "automate",     icon: Zap,       label: "Automate a task",          hint: "System control" },
];

// ─── Language Badge ───────────────────────────────────────────────────────────
function LanguageBadge({ lang }) {
  if (!lang || lang === "en" || lang === "auto") return null;
  const meta = LANG_META[lang];
  if (!meta) return null;
  return (
    <div className="titlebar-badge" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
      <Languages size={11} />
      <span>{meta.flag} {meta.name}</span>
    </div>
  );
}

// ─── Formatted Markdown & List Message ────────────────────────────────────────
function FormattedMessage({ content }) {
  if (!content) return null;

  let cleanContent = content;
  if (cleanContent.includes("&")) {
    try {
      const doc = new DOMParser().parseFromString(cleanContent, "text/html");
      cleanContent = doc.body.textContent || cleanContent;
    } catch {}
  }

  const renderInline = (str, keyPrefix = "") => {
    const parts = [];
    const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let lastIdx = 0;
    let match;

    while ((match = regex.exec(str)) !== null) {
      if (match.index > lastIdx) {
        parts.push(str.substring(lastIdx, match.index));
      }
      const token = match[0];
      if (token.startsWith("**") && token.endsWith("**")) {
        parts.push(<strong key={`${keyPrefix}-${match.index}`} className="ai-bold">{token.slice(2, -2)}</strong>);
      } else if (token.startsWith("`") && token.endsWith("`")) {
        parts.push(<code key={`${keyPrefix}-${match.index}`} className="ai-code">{token.slice(1, -1)}</code>);
      }
      lastIdx = regex.lastIndex;
    }
    if (lastIdx < str.length) {
      parts.push(str.substring(lastIdx));
    }
    return parts;
  };

  const lines = cleanContent.split("\n");
  const elements = [];
  let inCode = false;
  let codeBuffer = [];
  let codeLang = "";

  lines.forEach((line, idx) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        elements.push(
          <div key={`code-${idx}`} className="code-block-container">
            <div className="code-block-header">
              <span>{codeLang || "Code"}</span>
            </div>
            <pre className="ai-code-block">
              <code>{codeBuffer.join("\n")}</code>
            </pre>
          </div>
        );
        inCode = false;
        codeBuffer = [];
        codeLang = "";
      } else {
        inCode = true;
        codeLang = line.trim().slice(3).trim();
      }
      return;
    }

    if (inCode) {
      codeBuffer.push(line);
      return;
    }

    const trimmed = line.trim();
    if (trimmed.startsWith("# ")) {
      elements.push(<h2 key={idx} className="ai-heading-1">{renderInline(trimmed.substring(2), `h1-${idx}`)}</h2>);
    } else if (trimmed.startsWith("## ")) {
      elements.push(<h3 key={idx} className="ai-heading-2">{renderInline(trimmed.substring(3), `h2-${idx}`)}</h3>);
    } else if (trimmed.startsWith("### ")) {
      elements.push(<h4 key={idx} className="ai-heading-3">{renderInline(trimmed.substring(4), `h3-${idx}`)}</h4>);
    } else if (trimmed.startsWith("• ") || trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      elements.push(
        <div key={idx} style={{ display: "flex", gap: "8px", margin: "4px 0 4px 12px" }}>
          <span style={{ color: "var(--accent)" }}>•</span>
          <span>{renderInline(trimmed.substring(2), `item-${idx}`)}</span>
        </div>
      );
    } else if (/^\d+\.\s/.test(trimmed)) {
      const match = trimmed.match(/^(\d+)\.\s(.*)/);
      elements.push(
        <div key={idx} style={{ display: "flex", gap: "8px", margin: "4px 0 4px 12px" }}>
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>{match[1]}.</span>
          <span>{renderInline(match[2], `num-${idx}`)}</span>
        </div>
      );
    } else if (trimmed.length > 0) {
      elements.push(<p key={idx}>{renderInline(line, `p-${idx}`)}</p>);
    } else {
      elements.push(<div key={idx} style={{ height: "6px" }} />);
    }
  });

  return <div className="ai-formatted-text">{elements}</div>;
}

// ─── Response Card (Contextual summaries & outputs) ───────────────────────────
function ResponseCard({ task, message }) {
  if (!task || !message) {
    return <div className="ai-response-card">{message ? <FormattedMessage content={message} /> : "…"}</div>;
  }

  const cmd = task.command;
  const lang = task.language || "en";

  // Mail Inbox Read card
  if (cmd === "read_mail" && task.status === "completed") {
    const emails = task.auditTrail?.find(e => e.data?.emails)?.data?.emails || [];
    return (
      <div className="result-card mail-card">
        <div className="result-card-header">
          <div className="result-card-icon mail-icon"><Inbox size={15} /></div>
          <span>Inbox Overview</span>
          <LanguageBadge lang={lang} />
          <span style={{ marginLeft: "auto", fontSize: "11px", color: "var(--text-muted)" }}>{emails.length} messages</span>
        </div>
        {emails.length > 0 ? (
          <div className="mail-list">
            {emails.map((email, i) => (
              <div key={i} className="mail-item">
                <div className="mail-from"><AtSign size={11} /><span>{email.sender}</span></div>
                <div className="mail-subject">{email.subject}</div>
                {email.snippet && <div className="mail-snippet">{email.snippet}</div>}
                <div className="mail-date"><Clock size={10} />{email.date}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mail-empty">✓ Your mailbox is completely up to date.</div>
        )}
      </div>
    );
  }

  // Mail Summarize card
  if (cmd === "summarize_mail" && task.status === "completed") {
    return (
      <div className="result-card mail-card">
        <div className="result-card-header">
          <div className="result-card-icon mail-icon"><Mail size={15} /></div>
          <span>Email Summary</span>
          <LanguageBadge lang={lang} />
        </div>
        <FormattedMessage content={message} />
      </div>
    );
  }

  // Mail Draft Created card
  if (cmd === "draft_mail" && task.status === "completed") {
    const p = task.params || {};
    const toDisplay = p.recipient_email && p.recipient && p.recipient !== p.recipient_email
      ? `${p.recipient} <${p.recipient_email}>`
      : (p.recipient || p.recipient_email);
    const bodyContent = p.formatted_body || p.body;
    return (
      <div className="result-card draft-card">
        <div className="result-card-header">
          <div className="result-card-icon draft-icon"><FileEdit size={15} /></div>
          <span>Draft Prepared</span>
          <LanguageBadge lang={lang} />
        </div>
        <div className="draft-fields">
          {toDisplay && <div className="draft-field"><span className="draft-label">To</span><span className="draft-value">{toDisplay}</span></div>}
          {p.sender_account && <div className="draft-field"><span className="draft-label">From</span><span className="draft-value">{p.sender_account}</span></div>}
          {p.subject && <div className="draft-field"><span className="draft-label">Subject</span><span className="draft-value">{p.subject}</span></div>}
          {p.attachments && p.attachments.length > 0 && <div className="draft-field"><span className="draft-label">Attachments</span><span className="draft-value">{p.attachments.join(", ")}</span></div>}
          {bodyContent && <div className="draft-field"><span className="draft-label">Body</span><span className="draft-value" style={{ whiteSpace: "pre-wrap" }}>{bodyContent}</span></div>}
        </div>
        <div style={{ marginTop: "10px", fontSize: "11.5px", color: "var(--good)" }}>✓ Ready in mailbox. Review or ask Cortex to send when satisfied.</div>
      </div>
    );
  }

  // Generic card with markdown
  return (
    <div className="ai-response-card">
      {lang && lang !== "en" && <LanguageBadge lang={lang} />}
      <FormattedMessage content={message} />
    </div>
  );
}

// ─── Settings Modal ───────────────────────────────────────────────────────────
function SettingsModal({
  onClose,
  theme,
  setTheme,
  reducedMotion,
  setReducedMotion,
  speakingRate,
  setSpeakingRate,
  chimesEnabled,
  setChimesEnabled,
  wakeWordEnabled,
  setWakeWordEnabled,
  preferredLang,
  setPreferredLang,
  onClearHistory,
}) {
  const [tab, setTab] = useState("voice");
  const [memories, setMemories] = useState([]);
  const [loadingMem, setLoadingMem] = useState(false);

  const fetchMemories = useCallback(async () => {
    setLoadingMem(true);
    try {
      const res = await fetch(`${API}/memory`);
      const data = await res.json();
      setMemories(data.items || []);
    } catch {
      setMemories([]);
    } finally {
      setLoadingMem(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "memory") {
      fetchMemories();
    }
  }, [tab, fetchMemories]);

  async function handleDeleteMemory(id) {
    try {
      await fetch(`${API}/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
      setMemories(mems => mems.filter(m => m.id !== id));
    } catch (err) {
      console.warn("Delete memory failed:", err);
    }
  }

  async function handleClearAllMemories() {
    if (!window.confirm("Are you sure you want to delete all remembered facts and preferences?")) return;
    try {
      await fetch(`${API}/memory`, { method: "DELETE" });
      setMemories([]);
    } catch (err) {
      console.warn("Clear memories failed:", err);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <Settings size={18} />
            <span>Cortex Settings</span>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close settings">
            <X size={15} />
          </button>
        </div>

        <div className="modal-tabs">
          <button className={`modal-tab-btn ${tab === "voice" ? "active" : ""}`} onClick={() => setTab("voice")}>
            Voice & Speech
          </button>
          <button className={`modal-tab-btn ${tab === "appearance" ? "active" : ""}`} onClick={() => setTab("appearance")}>
            Appearance
          </button>
          <button className={`modal-tab-btn ${tab === "memory" ? "active" : ""}`} onClick={() => setTab("memory")}>
            Memory & Trust
          </button>
          <button className={`modal-tab-btn ${tab === "about" ? "active" : ""}`} onClick={() => setTab("about")}>
            About
          </button>
        </div>

        <div className="modal-body">
          {tab === "voice" && (
            <>
              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Hands-free 'Hey Cortex'</span>
                  <span className="setting-desc">Listen continuously for the wake phrase when mic is active</span>
                </div>
                <input
                  type="checkbox"
                  checked={wakeWordEnabled}
                  onChange={e => setWakeWordEnabled(e.target.checked)}
                />
              </div>

              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Speaking Rate ({speakingRate}x)</span>
                  <span className="setting-desc">Adjust spoken response velocity</span>
                </div>
                <input
                  type="range"
                  min="0.8"
                  max="1.4"
                  step="0.05"
                  className="setting-range"
                  value={speakingRate}
                  onChange={e => setSpeakingRate(parseFloat(e.target.value))}
                />
              </div>

              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Primary Response Language</span>
                  <span className="setting-desc">Cortex also automatically detects Kannada, Hindi, Tamil, Telugu, and English</span>
                </div>
                <select
                  className="setting-select"
                  value={preferredLang}
                  onChange={e => setPreferredLang(e.target.value)}
                >
                  <option value="auto">Auto Detect</option>
                  <option value="en">English</option>
                  <option value="kn">ಕನ್ನಡ (Kannada)</option>
                  <option value="hi">हिन्दी (Hindi)</option>
                  <option value="ta">தமிழ் (Tamil)</option>
                  <option value="te">తెలుగు (Telugu)</option>
                </select>
              </div>

              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Acoustic Audio Chimes</span>
                  <span className="setting-desc">Play melodic tones on activation, wake detection, and approvals</span>
                </div>
                <input
                  type="checkbox"
                  checked={chimesEnabled}
                  onChange={e => setChimesEnabled(e.target.checked)}
                />
              </div>
            </>
          )}

          {tab === "appearance" && (
            <>
              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Theme Palette</span>
                  <span className="setting-desc">Warm Claude Parchment or Anthropic Near Black</span>
                </div>
                <select
                  className="setting-select"
                  value={theme}
                  onChange={e => setTheme(e.target.value)}
                >
                  <option value="light">Claude Light (Parchment & Terracotta)</option>
                  <option value="dark">Claude Dark (Anthropic Near Black)</option>
                  <option value="system">Follow macOS System</option>
                </select>
              </div>

              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-title">Reduced Motion</span>
                  <span className="setting-desc">Diminish animations and orbital rotation for sensitive eyes</span>
                </div>
                <input
                  type="checkbox"
                  checked={reducedMotion}
                  onChange={e => setReducedMotion(e.target.checked)}
                />
              </div>

              <div className="setting-row" style={{ marginTop: "10px", paddingTop: "12px", borderTop: "1px solid var(--border)" }}>
                <div className="setting-info">
                  <span className="setting-title">Clear Current Session</span>
                  <span className="setting-desc">Start a fresh conversation without losing persisted memories</span>
                </div>
                <button
                  className="btn-draft-action cancel"
                  onClick={() => {
                    onClearHistory();
                    onClose();
                  }}
                >
                  <Trash2 size={13} /> Clear Session
                </button>
              </div>
            </>
          )}

          {tab === "memory" && (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div className="setting-info">
                  <span className="setting-title">Encrypted Memory Store</span>
                  <span className="setting-desc">Facts, user preferences, and contacts stored locally with AES-256</span>
                </div>
                {memories.length > 0 && (
                  <button
                    className="btn-draft-action cancel"
                    style={{ color: "var(--bad)" }}
                    onClick={handleClearAllMemories}
                  >
                    Clear All
                  </button>
                )}
              </div>

              {loadingMem ? (
                <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "16px" }}>Loading memories…</div>
              ) : memories.length === 0 ? (
                <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "16px", fontStyle: "italic" }}>
                  No stored memories yet. Cortex learns your preferences as you converse.
                </div>
              ) : (
                <div className="memory-list">
                  {memories.map(mem => (
                    <div key={mem.id} className="memory-item">
                      <span className="memory-item-kind">{mem.kind}</span>
                      <span className="memory-item-text">{JSON.stringify(mem.payload)}</span>
                      <button
                        className="memory-del-btn"
                        onClick={() => handleDeleteMemory(mem.id)}
                        title="Delete this memory"
                        aria-label="Delete memory"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ marginTop: "14px", padding: "12px", borderRadius: "var(--radius-sm)", background: "rgba(91, 158, 246, 0.08)", border: "1px solid rgba(91, 158, 246, 0.2)", fontSize: "12px", lineHeight: "1.5", color: "var(--text-muted)" }}>
                <Shield size={14} style={{ verticalAlign: "middle", marginRight: "6px", color: "var(--accent)" }} />
                <strong>Security Guarantee:</strong> Consequential actions (such as sending emails or deleting data) always require your deliberate cryptographic authorization. No silent background execution.
              </div>
            </>
          )}

          {tab === "about" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "13px", lineHeight: "1.6", color: "var(--text-muted)" }}>
              <div style={{ fontSize: "16px", fontWeight: 700, color: "var(--text)" }}>Cortex v0.3</div>
              <p>Personal, voice-first AI desktop companion inspired by the elegance, simplicity, and responsiveness of Apple Siri.</p>
              <p>Powered by local speech processing, Gemini multimodal reasoning, Apple Mail automation, and zero-trust human-in-the-loop permission verification.</p>
              <div style={{ marginTop: "8px", fontSize: "11.5px", color: "var(--text-subtle)" }}>
                Keyboard shortcuts: <strong>⌘K</strong> Command Palette • <strong>⌘,</strong> Settings • <strong>Esc</strong> Interrupt Speech
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Edit Draft Modal (Server-Verified SHA-256) ───────────────────────────────
function EditDraftModal({ task, onClose, onSave, onSaveAndApprove }) {
  const p = task?.params || {};
  const [recipient, setRecipient]   = useState(p.recipient_email || p.recipient || "");
  const [subject, setSubject]       = useState(p.subject || "");
  const [body, setBody]             = useState(p.formatted_body || p.body || "");
  const [attachments, setAttachments] = useState(
    Array.isArray(p.attachments) ? p.attachments.join(", ") : (p.attachments || "")
  );
  const [isSaving, setIsSaving] = useState(false);

  async function handleSave() {
    setIsSaving(true);
    try {
      await onSave({ recipient, subject, body, attachments });
    } finally {
      setIsSaving(false);
    }
  }

  async function handleApprove() {
    setIsSaving(true);
    try {
      await onSaveAndApprove({ recipient, subject, body, attachments });
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <FileEdit size={16} />
            <span>Edit Email Draft</span>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close edit draft">
            <X size={15} />
          </button>
        </div>

        <div className="draft-modal-fields">
          <div className="draft-modal-row">
            <label>Recipient (To)</label>
            <input value={recipient} onChange={e => setRecipient(e.target.value)} placeholder="recipient@example.com" />
          </div>
          <div className="draft-modal-row">
            <label>Subject</label>
            <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Email subject" />
          </div>
          <div className="draft-modal-row">
            <label>Attachments (comma-separated file paths)</label>
            <input value={attachments} onChange={e => setAttachments(e.target.value)} placeholder="/path/to/file.pdf" />
          </div>
          <div className="draft-modal-row">
            <label>Body Content</label>
            <textarea rows={7} value={body} onChange={e => setBody(e.target.value)} placeholder="Type email body…" />
          </div>
        </div>

        <div className="draft-modal-actions">
          <button className="btn-draft-action cancel" onClick={onClose} disabled={isSaving}>
            Cancel
          </button>
          <button className="btn-draft-action save" onClick={handleSave} disabled={isSaving}>
            <Check size={14} /> Update Draft
          </button>
          <button className="btn-draft-action send" onClick={handleApprove} disabled={isSaving}>
            <Send size={14} /> Update & Approve Send
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Command Palette ──────────────────────────────────────────────────────────
function CommandPalette({ onClose, onCommand, onDraftModal, onOpenSettings }) {
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
    if (cmd.id === "settings") {
      onOpenSettings();
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
          <span className="palette-item-kbd">ESC to close</span>
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

// ─── Main App Component ───────────────────────────────────────────────────────
function App() {
  const [message, setMessage]               = useState("");
  const [turns, setTurns]                   = useState([]);
  const [task, setTask]                     = useState(null);
  const [assistant, setAssistant]           = useState("Hey — I'm Cortex. What shall we do?");
  const [loading, setLoading]               = useState(false);
  const [listening, setListening]           = useState(false);
  const [paletteOpen, setPaletteOpen]       = useState(false);
  const [settingsOpen, setSettingsOpen]     = useState(false);
  const [editModalOpen, setEditModalOpen]   = useState(false);
  const [audioEnabled, setAudioEnabled]     = useState(false);
  const [detectedLang, setDetectedLang]     = useState("en");
  const [voiceState, setVoiceState]         = useState("disabled");
  const [wakeWordEnabled, setWakeWordEnabled] = useState(true);
  const [speakingRate, setSpeakingRate]     = useState(1.0);
  const [chimesEnabled, setChimesEnabled]   = useState(true);
  const [preferredLang, setPreferredLang]   = useState("auto");
  const [theme, setTheme]                   = useState("light");
  const [reducedMotion, setReducedMotion]   = useState(false);
  const [isFloating, setIsFloating]         = useState(false);

  const turnsEndRef           = useRef(null);
  const wakeRecognizerRef     = useRef(null);
  const wakeWordActiveRef     = useRef(true);
  const voiceStateRef         = useRef("disabled");
  const audioActiveRef        = useRef(false);
  const isSpeakingRef         = useRef(false);
  const isListeningRef        = useRef(false);
  const audioCtxRef           = useRef(null);
  const mediaStreamRef        = useRef(null);
  const processorRef          = useRef(null);
  const userAudioChunksRef    = useRef([]);
  const isRecordingUserRef    = useRef(false);
  const lastVoiceTimeRef      = useRef(0);
  const sendMessageRef        = useRef(null);
  const startWakeWordSpotterRef = useRef(null);
  const startAudioPipelineRef   = useRef(null);

  // Sync refs & DOM themes
  useEffect(() => {
    wakeWordActiveRef.current = wakeWordEnabled;
  }, [wakeWordEnabled]);

  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-reduced-motion", reducedMotion ? "true" : "false");
  }, [reducedMotion]);

  // Auto-scroll turns
  useEffect(() => {
    turnsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, task]);

  // IPC: sync HUD window
  useEffect(() => {
    if (!ipc || !task) return;
    if (["running", "executing"].includes(task.status)) {
      ipc.send("hud-show", { intent: task.intent, steps: task.auditTrail });
    } else {
      ipc.send("hud-hide");
    }
  }, [task]);

  // IPC: sync window mode (floating assistant vs full workspace)
  useEffect(() => {
    if (!ipc) return;
    const onModeChanged = (_, mode) => setIsFloating(mode === "floating");
    ipc.on("window-mode-changed", onModeChanged);
    ipc.invoke("get-window-mode").then(mode => {
      if (mode === "floating") setIsFloating(true);
    }).catch(() => {});
    return () => {
      ipc.removeListener("window-mode-changed", onModeChanged);
    };
  }, []);

  function toggleFloatingMode() {
    const next = !isFloating;
    setIsFloating(next);
    if (ipc) {
      ipc.send("set-window-mode", next ? "floating" : "standard");
    }
  }

  // Global keyboard shortcuts (⌘K for palette, ⌘, for settings, Esc to stop speaking)
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen(p => !p);
      } else if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        setSettingsOpen(s => !s);
      } else if (e.key === "Escape") {
        if (voiceState === "speaking" || isSpeakingRef.current) {
          interruptSpeech();
        } else if (paletteOpen) {
          setPaletteOpen(false);
        } else if (settingsOpen) {
          setSettingsOpen(false);
        } else if (editModalOpen) {
          setEditModalOpen(false);
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [voiceState, paletteOpen, settingsOpen, editModalOpen]);

  // ─── Audio Chimes ───────────────────────────────────────────────────────────
  function playChime(type = "activate") {
    if (!chimesEnabled) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      if (type === "activate") {
        [523.25, 659.25, 783.99].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now + idx * 0.06);
          gain.gain.setValueAtTime(0, now + idx * 0.06);
          gain.gain.linearRampToValueAtTime(0.12, now + idx * 0.06 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.06 + 0.24);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.06); osc.stop(now + idx * 0.06 + 0.26);
        });
      } else if (type === "deactivate") {
        [659.25, 523.25].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now + idx * 0.07);
          gain.gain.setValueAtTime(0, now + idx * 0.07);
          gain.gain.linearRampToValueAtTime(0.09, now + idx * 0.07 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.07 + 0.20);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.07); osc.stop(now + idx * 0.07 + 0.22);
        });
      } else if (type === "success") {
        [587.33, 880.00].forEach((freq) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now);
          gain.gain.setValueAtTime(0.1, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now); osc.stop(now + 0.34);
        });
      } else if (type === "wake") {
        [783.99, 1046.50].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "sine"; osc.frequency.setValueAtTime(freq, now + idx * 0.08);
          gain.gain.setValueAtTime(0, now + idx * 0.08);
          gain.gain.linearRampToValueAtTime(0.12, now + idx * 0.08 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.26);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.08); osc.stop(now + idx * 0.08 + 0.28);
        });
      } else if (type === "alert") {
        [440, 554.37].forEach((freq, idx) => {
          const osc = ctx.createOscillator(); const gain = ctx.createGain();
          osc.type = "triangle"; osc.frequency.setValueAtTime(freq, now + idx * 0.1);
          gain.gain.setValueAtTime(0.08, now + idx * 0.1);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.1 + 0.16);
          osc.connect(gain); gain.connect(ctx.destination);
          osc.start(now + idx * 0.1); osc.stop(now + idx * 0.1 + 0.18);
        });
      }
    } catch {}
  }

  // ─── Audio Helpers ──────────────────────────────────────────────────────────
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

  // ─── Speak Response with Natural Voice & Interruption Support ───────────────
  const interruptSpeech = useCallback(() => {
    if (window._cortexNativeAudio) {
      try { window._cortexNativeAudio.pause(); } catch {}
      window._cortexNativeAudio = null;
    }
    if ("speechSynthesis" in window) {
      try { window.speechSynthesis.cancel(); } catch {}
    }
    if (window._speechSafetyTimeout) clearTimeout(window._speechSafetyTimeout);
    isSpeakingRef.current = false;

    if (audioActiveRef.current) {
      setVoiceState("standby");
      setAssistant("Listening for 'Hey Cortex' or tap to speak…");
      if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
    } else {
      setVoiceState("disabled");
    }
  }, []);

  function fallbackWebSpeech(speech, langCode, onDone) {
    if (!("speechSynthesis" in window)) { if (onDone) onDone(); return; }
    try {
      const utterance = new SpeechSynthesisUtterance(speech);
      utterance.rate = speakingRate || 1.0;
      utterance.pitch = 1.02;

      const targetBcp = LANG_META[langCode]?.bcp || "en-US";
      const voices = window.speechSynthesis.getVoices();

      let chosen = null;
      if (langCode !== "en") {
        chosen =
          voices.find(v => v.lang === targetBcp && (v.name.includes("Enhanced") || v.name.includes("Premium"))) ||
          voices.find(v => v.lang === targetBcp) ||
          voices.find(v => v.lang.startsWith(langCode));
      }
      if (!chosen) {
        chosen =
          voices.find(v => v.lang.startsWith("en") && (v.name.includes("Enhanced") || v.name.includes("Premium") || v.name.includes("Natural"))) ||
          voices.find(v => v.lang.startsWith("en") && (v.name.includes("Samantha") || v.name.includes("Ava") || v.name.includes("Daniel") || v.name.includes("Serena"))) ||
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
        if (audioActiveRef.current) {
          setVoiceState("standby");
          setAssistant("Listening for 'Hey Cortex' or tap to speak…");
          if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
        } else {
          setVoiceState("disabled");
        }
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
      if (audioActiveRef.current) {
        setVoiceState("standby");
        if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
      }
      if (onDone) onDone();
    }
  }

  function speakText(text, langCode = "en", onDone) {
    try {
      if (window._cortexNativeAudio) {
        try { window._cortexNativeAudio.pause(); } catch {}
        window._cortexNativeAudio = null;
      }
      if ("speechSynthesis" in window) {
        try { window.speechSynthesis.cancel(); } catch {}
      }
      isSpeakingRef.current = true;
      setVoiceState("speaking");
      stopWakeWordSpotter();

      let decoded = text || "";
      if (decoded.includes("&")) {
        try {
          const doc = new DOMParser().parseFromString(decoded, "text/html");
          decoded = doc.body.textContent || decoded;
        } catch {}
      }

      let speech = decoded
        .replace(/```[\s\S]*?```/g, "")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/https?:\/\/\S+/g, "")
        .replace(/[*_#~>[\]]/g, "")
        .replace(/^\s*[-•*]\s+/gm, "")
        .replace(/^\s*\d+\.\s+/gm, "")
        .replace(/\s+/g, " ")
        .trim();

      if (!speech) {
        isSpeakingRef.current = false;
        if (audioActiveRef.current) {
          setVoiceState("standby");
          if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
        }
        if (onDone) onDone();
        return;
      }

      // Pristine native audio for multilingual voices (Kannada, Hindi, Tamil, Telugu) or if WebSpeech not optimal
      if (langCode !== "en" || !("speechSynthesis" in window)) {
        try {
          const ttsUrl = `${API}/tts?text=${encodeURIComponent(speech.slice(0, 500))}&lang=${encodeURIComponent(langCode)}`;
          const audio = new Audio(ttsUrl);
          window._cortexNativeAudio = audio;

          let nativeFinished = false;
          const handleNativeDone = () => {
            if (nativeFinished) return;
            nativeFinished = true;
            isSpeakingRef.current = false;
            window._cortexNativeAudio = null;
            if (window._speechSafetyTimeout) clearTimeout(window._speechSafetyTimeout);
            if (audioActiveRef.current) {
              setVoiceState("standby");
              setAssistant("Listening for 'Hey Cortex' or tap to speak…");
              if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
            } else {
              setVoiceState("disabled");
            }
            if (onDone) onDone();
          };

          audio.onended = handleNativeDone;
          audio.onerror = () => fallbackWebSpeech(speech, langCode, onDone);
          const playPromise = audio.play();
          if (playPromise !== undefined) {
            playPromise.catch(() => fallbackWebSpeech(speech, langCode, onDone));
          }
          const maxDur = Math.max(4000, speech.length * 150);
          window._speechSafetyTimeout = setTimeout(handleNativeDone, maxDur);
          return;
        } catch {
          fallbackWebSpeech(speech, langCode, onDone);
          return;
        }
      }

      fallbackWebSpeech(speech, langCode, onDone);
    } catch {
      isSpeakingRef.current = false;
      if (audioActiveRef.current) {
        setVoiceState("standby");
        if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
      }
      if (onDone) onDone();
    }
  }

  // ─── Wake Word Spotter ("Hey Cortex") ───────────────────────────────────────
  const stopWakeWordSpotter = useCallback(() => {
    if (wakeRecognizerRef.current) {
      try {
        wakeRecognizerRef.current.onend = null;
        wakeRecognizerRef.current.abort();
      } catch {}
      wakeRecognizerRef.current = null;
    }
  }, []);

  const startWakeWordSpotter = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    if (wakeRecognizerRef.current) {
      try {
        wakeRecognizerRef.current.onend = null;
        wakeRecognizerRef.current.abort();
      } catch {}
      wakeRecognizerRef.current = null;
    }

    try {
      const recognizer = new SpeechRecognition();
      recognizer.continuous = true;
      recognizer.interimResults = true;
      recognizer.maxAlternatives = 1;
      recognizer.lang = "en-US";

      recognizer.onresult = (event) => {
        if (!audioActiveRef.current || isSpeakingRef.current || isRecordingUserRef.current) return;

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i];
          const transcriptText = res[0]?.transcript?.trim().toLowerCase() || "";

          const match = transcriptText.match(/\b(?:hey\s+|ok\s+|okay\s+|hi\s+|hello\s+)?cortex\b/i);
          if (match) {
            playChime("wake");
            setVoiceState("wake_detected");
            setAssistant("Hey! I'm listening…");

            try {
              recognizer.onend = null;
              recognizer.abort();
            } catch {}

            const afterWake = transcriptText.slice(match.index + match[0].length).trim();
            if (afterWake.length > 2) {
              setVoiceState("thinking");
              if (sendMessageRef.current) {
                sendMessageRef.current("voice", afterWake);
              }
              return;
            }

            setTimeout(() => {
              if (audioActiveRef.current && !isSpeakingRef.current) {
                setVoiceState("capturing");
                if (startAudioPipelineRef.current) {
                  startAudioPipelineRef.current();
                }
              }
            }, 300);
            return;
          }
        }
      };

      recognizer.onerror = (e) => {
        if (e.error !== "aborted" && e.error !== "no-speech") {
          console.warn("[cortex] Wake recognizer:", e.error);
        }
      };

      recognizer.onend = () => {
        if (audioActiveRef.current && !isSpeakingRef.current && !isRecordingUserRef.current && wakeWordActiveRef.current) {
          try { recognizer.start(); } catch {}
        }
      };

      recognizer.start();
      wakeRecognizerRef.current = recognizer;
    } catch (err) {
      console.warn("[cortex] Wake setup error:", err);
    }
  }, []);
  startWakeWordSpotterRef.current = startWakeWordSpotter;

  // ─── Send Message (Voice or Text Parity) ─────────────────────────────────────
  const sendMessage = useCallback(async (source = "text", override = "") => {
    const text = (override || message).trim();
    if (!text) return;

    setVoiceState("thinking");
    setLoading(true);
    setMessage("");
    setAssistant("…");

    const turnId = Date.now();
    const newTurn = {
      id: turnId,
      source,
      query: text,
      response: "…",
      task: null,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setTurns(prev => [...prev, newTurn]);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, source }),
      });
      const data = await res.json();
      const lang = data.task?.language || "en";
      setDetectedLang(lang);
      setAssistant(data.message);
      setTask(data.task || null);

      setTurns(prev => prev.map(t => t.id === turnId ? {
        ...t,
        response: data.message,
        task: data.task || null,
        language: lang,
      } : t));

      if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
        setVoiceState("confirming");
        playChime("alert");
      } else if (data.task?.status === "completed") {
        playChime("success");
      }

      setVoiceState("speaking");
      speakText(data.message, lang, () => {
        if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
          setVoiceState("confirming");
        } else if (audioActiveRef.current) {
          setVoiceState("standby");
          setAssistant("Listening for 'Hey Cortex' or tap to speak…");
          if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
        } else {
          setVoiceState("disabled");
        }
      });
    } catch {
      const errMsg = "Could not connect to Cortex. Please ensure the backend server is running.";
      setAssistant(`⚠ ${errMsg}`);
      setTurns(prev => prev.map(t => t.id === turnId ? { ...t, response: errMsg } : t));
      speakText(errMsg, "en");
    } finally {
      setLoading(false);
    }
  }, [message]);
  sendMessageRef.current = sendMessage;

  // ─── Audio Recording & VAD ──────────────────────────────────────────────────
  const stopAudioPipeline = useCallback(() => {
    isListeningRef.current = false;
    isRecordingUserRef.current = false;
    setListening(false);
    if (processorRef.current) { try { processorRef.current.disconnect(); } catch {} processorRef.current = null; }
    if (audioCtxRef.current)  { try { audioCtxRef.current.close(); } catch {} audioCtxRef.current = null; }
    if (mediaStreamRef.current) { try { mediaStreamRef.current.getTracks().forEach(t => t.stop()); } catch {} mediaStreamRef.current = null; }
  }, []);

  const sendAudioChunk = useCallback(async (chunks, sampleRate) => {
    if (!chunks || chunks.length === 0) return;
    let totalLen = 0;
    for (const c of chunks) totalLen += c.length;
    if (totalLen < 6000) return;

    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const c of chunks) { merged.set(c, offset); offset += c.length; }

    const wavBlob = encodeWAV(downsampleBuffer(merged, sampleRate, 16000), 16000);

    setVoiceState("transcribing");
    setLoading(true);
    setAssistant("Transcribing audio…");

    const turnId = Date.now();
    try {
      const res = await fetch(`${API}/audio_chat`, {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: wavBlob,
      });
      const data = await res.json();
      const lang = data.task?.language || "en";
      setDetectedLang(lang);
      setAssistant(data.message);
      setTask(data.task || null);

      if (data.transcript) {
        setTurns(prev => [...prev, {
          id: turnId,
          source: "voice",
          query: data.transcript,
          response: data.message,
          task: data.task || null,
          language: lang,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }]);
      }

      if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
        setVoiceState("confirming");
        playChime("alert");
      } else if (data.task?.status === "completed") {
        playChime("success");
      }

      setVoiceState("speaking");
      speakText(data.message, lang, () => {
        if (data.task?.requiresApproval && data.task?.status === "waiting_approval") {
          setVoiceState("confirming");
        } else if (audioActiveRef.current) {
          setVoiceState("standby");
          setAssistant("Listening for 'Hey Cortex' or tap to speak…");
          if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
        } else {
          setVoiceState("disabled");
        }
      });
    } catch {
      setAssistant("Could not connect to Cortex brain.");
      if (audioActiveRef.current) {
        setVoiceState("standby");
        if (wakeWordActiveRef.current) startWakeWordSpotterRef.current?.();
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const startAudioPipeline = useCallback(async () => {
    if (!audioActiveRef.current) return;
    stopAudioPipeline();
    stopWakeWordSpotter();
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
            setVoiceState("capturing");
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
      setVoiceState("capturing");
      setAssistant("Listening — speak your request…");
    } catch (err) {
      console.warn("Microphone access failed:", err);
      audioActiveRef.current = false;
      setAudioEnabled(false);
      setVoiceState("disabled");
      setAssistant("Microphone access blocked. Please enable microphone permissions in System Settings.");
    }
  }, [stopAudioPipeline, stopWakeWordSpotter, sendAudioChunk]);
  startAudioPipelineRef.current = startAudioPipeline;

  // ─── Toggle Voice Audio ─────────────────────────────────────────────────────
  async function toggleAudio() {
    if (audioEnabled) {
      playChime("deactivate");
      audioActiveRef.current = false;
      setAudioEnabled(false);
      setVoiceState("disabled");
      stopWakeWordSpotter();
      stopAudioPipeline();
      interruptSpeech();
      setAssistant("Voice assistant deactivated.");
    } else {
      playChime("activate");
      audioActiveRef.current = true;
      setAudioEnabled(true);
      setVoiceState("standby");
      setAssistant("Hands-free activated. Say 'Hey Cortex' or tap the orb to speak!");
      speakText("I'm ready. Say Hey Cortex anytime.", "en", () => {
        setVoiceState("standby");
        if (wakeWordActiveRef.current) {
          startWakeWordSpotter();
        } else {
          startAudioPipeline();
        }
      });
    }
  }

  // ─── Orb Tap Handler (Push-to-Talk / Interrupt) ─────────────────────────────
  function handleOrbClick() {
    if (!audioEnabled) {
      toggleAudio();
      return;
    }
    if (voiceState === "speaking" || isSpeakingRef.current) {
      interruptSpeech();
      return;
    }
    if (voiceState === "capturing" || isRecordingUserRef.current) {
      stopAudioPipeline();
      return;
    }
    stopWakeWordSpotter();
    playChime("wake");
    setVoiceState("capturing");
    setAssistant("Listening to your request…");
    startAudioPipeline();
  }

  // ─── Cryptographic Action Approval / Rejection ──────────────────────────────
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
    const msg = approved ? "Approved. Executing action now." : "Action rejected.";
    setAssistant(msg);
    speakText(msg, lang, () => {
      setAssistant("Listening — speak anytime…");
    });
  }

  // ─── Server-Verified Draft Editing ──────────────────────────────────────────
  async function handleSaveEdit({ recipient, subject, body, attachments }) {
    if (!task) return;
    const attList = typeof attachments === "string"
      ? attachments.split(",").map(s => s.trim()).filter(Boolean)
      : (attachments || []);
    const res = await fetch(`${API}/tasks/${task.id}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recipient,
        subject,
        body,
        attachments: attList,
        sender_account: task.params?.sender_account
      }),
    });
    if (res.ok) {
      const updated = await res.json();
      setTask(updated.task || updated);
      setAssistant("Draft updated! Cryptographic approval hash recalculated. Review the revised draft and approve to send.");
      setEditModalOpen(false);
      playChime("success");
      return updated;
    } else {
      const err = await res.json().catch(() => ({}));
      setAssistant(`Failed to update draft: ${err.detail || "Server error"}`);
      playChime("alert");
      throw new Error(err.detail || "Edit failed");
    }
  }

  async function handleSaveAndApprove(fields) {
    await handleSaveEdit(fields);
    await decide(true);
  }

  // ─── Clear Session ──────────────────────────────────────────────────────────
  async function clearSession() {
    setTurns([]);
    setTask(null);
    setAssistant("Hey — I'm Cortex. What shall we do?");
    try {
      await fetch(`${API}/session/clear`, { method: "POST" });
    } catch {}
  }

  const orbState =
    voiceState === "speaking" ? "speaking" :
    voiceState === "wake_detected" ? "wake_detected" :
    voiceState === "capturing" || listening ? "capturing listening" :
    voiceState === "transcribing" || loading ? "transcribing thinking" :
    voiceState === "confirming" ? "confirming" :
    voiceState === "standby" ? "standby" : "";

  const currentLang = task?.language || detectedLang || "en";

  return (
    <div className={`app ${isFloating ? "floating-mode" : ""}`}>
      {/* ── macOS Titlebar ── */}
      <div className="titlebar">
        <div className="titlebar-brand">
          <div className="titlebar-logo-orb" />
          <span className="titlebar-label">Cortex</span>
          {currentLang !== "en" && (
            <div className="titlebar-badge" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
              <Languages size={11} />
              <span>{LANG_META[currentLang]?.name || currentLang}</span>
            </div>
          )}
        </div>

        <div className="titlebar-actions">
          {/* Status Pill */}
          <div className={`voice-status-pill ${voiceState}`}>
            <span className="voice-status-dot" />
            <span>
              {voiceState === "wake_detected" ? "Hey Cortex detected!" :
               voiceState === "capturing" ? "Listening to command…" :
               voiceState === "transcribing" ? "Transcribing speech…" :
               voiceState === "thinking" ? "Thinking…" :
               voiceState === "speaking" ? "Speaking response…" :
               voiceState === "confirming" ? "Awaiting your approval…" :
               voiceState === "standby" ? (wakeWordEnabled ? "Hands-Free ('Hey Cortex')" : "Push-to-Talk Ready") :
               "Voice Idle"}
            </span>
          </div>

          {/* Floating Assistant Mode Toggle */}
          <button
            className={`titlebar-btn ${isFloating ? "active" : ""}`}
            onClick={toggleFloatingMode}
            title={isFloating ? "Restore Standard Window (Full Workspace)" : "Pin as Floating Assistant (Always-on-top, ⌥Space to summon)"}
            aria-label="Toggle floating assistant window"
          >
            <Pin size={14} style={{ transform: isFloating ? "rotate(45deg)" : "none", transition: "transform 0.2s" }} />
          </button>

          {/* Theme Quick Toggle */}
          <button
            className="titlebar-btn"
            onClick={() => setTheme(t => t === "dark" ? "light" : "dark")}
            title={`Switch to ${theme === "dark" ? "Light" : "Dark"} theme`}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          </button>

          {/* Clear Session */}
          <button
            className="titlebar-btn"
            onClick={clearSession}
            title="Start new conversation session"
            aria-label="New session"
          >
            <History size={14} />
          </button>

          {/* Settings */}
          <button
            className="titlebar-btn"
            onClick={() => setSettingsOpen(true)}
            title="Open Settings (⌘,)"
            aria-label="Settings"
          >
            <Settings size={14} />
          </button>
        </div>
      </div>

      {/* ── Central Stage ── */}
      <div className="shell">
        <div className="stage">
          {/* Animated Siri-Inspired Cortex Orb */}
          <div className={`orb-wrap ${orbState}`} onClick={handleOrbClick}>
            <div className="orb-glow-field" />
            <div className="orb-ring orb-ring-3" />
            <div className="orb-ring orb-ring-2" />
            <div className="orb-ring orb-ring-1" />
            <button
              className="voiceButton"
              title={
                voiceState === "speaking" ? "Click to interrupt speech" :
                voiceState === "capturing" ? "Click to finish speaking" :
                audioEnabled ? "Click to speak (or say 'Hey Cortex')" : "Click to activate voice assistant"
              }
              aria-label="Voice Orb"
            >
              {voiceState === "speaking" ? <Volume2 size={48} /> :
               (listening || voiceState === "capturing") ? <MicOff size={48} /> :
               <Mic size={48} />}
            </button>
          </div>

          {/* Acoustic Waveform */}
          <div className={`waveform ${orbState}`} aria-hidden="true">
            {Array.from({ length: 24 }).map((_, i) => (
              <span key={i} style={{ "--i": i + 1 }} />
            ))}
          </div>

          {/* Floating Stop Speaking Pill when active */}
          {(voiceState === "speaking" || isSpeakingRef.current) && (
            <button className="stop-speaking-pill" onClick={interruptSpeech}>
              <VolumeX size={13} />
              <span>Stop Speaking (Esc)</span>
            </button>
          )}

          {/* Conversation History Stream */}
          <div className="conversation-stream">
            {turns.length === 0 ? (
              <div className="empty-stage-container">
                <h1 className="stage-headline">How can I assist you today?</h1>
              </div>
            ) : (
              turns.map((turn) => (
                <div key={turn.id} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {/* User Turn */}
                  <div className="turn-bubble turn-user">
                    <div className="turn-user-content">
                      {turn.source === "voice" ? <Mic size={14} style={{ color: "var(--warn)" }} /> : <Terminal size={14} />}
                      <span>{turn.query}</span>
                    </div>
                    <div className="turn-user-meta">
                      <span>{turn.timestamp}</span>
                    </div>
                  </div>

                  {/* Cortex Turn */}
                  <div className="turn-bubble turn-cortex">
                    <div className="turn-cortex-card">
                      <div className="turn-cortex-header">
                        <div className="turn-cortex-avatar">
                          <Sparkles size={14} style={{ color: "var(--accent)" }} />
                          <span>Cortex</span>
                          {turn.language && turn.language !== "en" && <LanguageBadge lang={turn.language} />}
                        </div>
                        <div className="turn-cortex-tools">
                          <button
                            className="turn-tool-btn"
                            onClick={() => speakText(turn.response, turn.language || "en")}
                            title="Read response aloud"
                          >
                            <Volume2 size={12} />
                          </button>
                          <button
                            className="turn-tool-btn"
                            onClick={() => navigator.clipboard.writeText(turn.response)}
                            title="Copy response"
                          >
                            <Copy size={12} />
                          </button>
                        </div>
                      </div>
                      <ResponseCard task={turn.task} message={turn.response} />
                    </div>
                  </div>
                </div>
              ))
            )}

            {/* Live Approval Card (Cryptographic Security Gate) */}
            {task?.requiresApproval && task.status === "waiting_approval" && (
              <div className="approval-card">
                <div className="approval-header">
                  <AlertTriangle size={16} />
                  <span>Consequential Action Requires Your Approval</span>
                </div>
                <div className="approval-desc">
                  Cortex proposes to execute: <strong>{task.command?.replace(/_/g, " ")}</strong>
                  {task.params?.recipient && <> → <em>{task.params.recipient}</em></>}
                  <br />
                  <span className="approval-hash-badge">
                    Approval SHA-256: {task.params?.approval_hash?.slice(0, 16)}…
                  </span>
                </div>
                <div className="approval-actions">
                  <button className="btn-approve" onClick={() => decide(true)}>
                    <Check size={14} /> Approve & Send
                  </button>
                  <button className="btn-edit" onClick={() => setEditModalOpen(true)}>
                    <FileEdit size={14} /> Edit Draft Details
                  </button>
                  <button className="btn-reject" onClick={() => decide(false)}>
                    <X size={14} /> Reject Action
                  </button>
                </div>
              </div>
            )}

            <div ref={turnsEndRef} />
          </div>
        </div>

        {/* ── Bottom Floating Dock ── */}
        <div className="dock">
          {/* Composer Input */}
          <div className="composer">
            <input
              className="composer-input"
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => e.key === "Enter" && sendMessage("text")}
              placeholder="Ask anything, type a command, or say 'Hey Cortex'…"
            />
            <button
              className="composer-btn primary"
              onClick={() => sendMessage("text")}
              disabled={loading || !message.trim()}
              title="Send text message"
            >
              <Send size={15} />
            </button>
            <button
              className={`composer-btn ${listening ? "listening" : ""}`}
              onClick={handleOrbClick}
              title={audioEnabled ? (listening ? "Mute mic" : "Tap to speak") : "Enable audio first"}
            >
              {listening ? <MicOff size={15} /> : <Mic size={15} />}
            </button>
          </div>
        </div>
      </div>

      {/* ── Modals & Drawers ── */}
      {paletteOpen && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onCommand={(cmd) => sendMessage("text", cmd)}
          onDraftModal={() => sendMessage("text", "draft an email")}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      )}

      {settingsOpen && (
        <SettingsModal
          onClose={() => setSettingsOpen(false)}
          theme={theme}
          setTheme={setTheme}
          reducedMotion={reducedMotion}
          setReducedMotion={setReducedMotion}
          speakingRate={speakingRate}
          setSpeakingRate={setSpeakingRate}
          chimesEnabled={chimesEnabled}
          setChimesEnabled={setChimesEnabled}
          wakeWordEnabled={wakeWordEnabled}
          setWakeWordEnabled={setWakeWordEnabled}
          preferredLang={preferredLang}
          setPreferredLang={setPreferredLang}
          onClearHistory={clearSession}
        />
      )}

      {editModalOpen && task?.status === "waiting_approval" && (
        <EditDraftModal
          task={task}
          onClose={() => setEditModalOpen(false)}
          onSave={handleSaveEdit}
          onSaveAndApprove={handleSaveAndApprove}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
