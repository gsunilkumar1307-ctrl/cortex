import React, { useState, useRef, useEffect } from "react";
import {
  Send, Square, Paperclip, Mic, X,
  FileText, Image as ImageIcon, Sparkles, Terminal,
  Globe, Mail, Calendar, Compass, Shield, Eye, HelpCircle,
  Folder, Sliders, Bot
} from "lucide-react";

const SLASH_COMMANDS = [
  { command: "/help", desc: "Show Cortex capabilities and command reference", icon: HelpCircle },
  { command: "/new", desc: "Start a fresh conversation thread", icon: Sparkles },
  { command: "/research", desc: "Perform evidence-based web research", icon: Globe },
  { command: "/summarize", desc: "Summarize previous discussion or document", icon: FileText },
  { command: "/plan", desc: "Decompose a complex 7-day project plan", icon: Calendar },
  { command: "/tasks", desc: "Show recent tasks and execution audit trail", icon: Terminal },
  { command: "/memory", desc: "View and manage user memories", icon: Shield },
  { command: "/settings", desc: "Open Cortex configuration and preferences", icon: Sliders },
  { command: "/voice", desc: "Toggle voice listening and TTS settings", icon: Mic },
  { command: "/stop", desc: "Stop running operations or speech", icon: Square },
];

const MENTIONS = [
  { tag: "@mail", label: "Apple Mail", desc: "Draft and review emails", icon: Mail },
  { tag: "@browser", label: "Web Browser", desc: "Safari & Chrome web research", icon: Compass },
  { tag: "@screen", label: "Screen Intelligence", desc: "Inspect active app and UI elements", icon: Eye },
  { tag: "@finder", label: "macOS Finder", desc: "Inspect files and folders", icon: Folder },
  { tag: "@whatsapp", label: "WhatsApp Desktop", desc: "Prepare messages with verification", icon: Bot },
  { tag: "@tasks", label: "Task Planner", desc: "Autonomous planning and tracking", icon: Terminal },
];

export function CortexComposer({
  onSend,
  onStop,
  isRunning,
  onOpenSettings,
  onOpenAudit,
  onNewThread,
  onAudioDictate,
  isListening,
}) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const [showMentionMenu, setShowMentionMenu] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);

  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(180, textareaRef.current.scrollHeight) + "px";
    }
  }, [text]);

  // Handle typing & popups (slash commands and mentions)
  const handleChange = (e) => {
    const val = e.target.value;
    setText(val);

    // Check for slash command trigger
    if (val.startsWith("/")) {
      const match = val.match(/^\/([a-zA-Z]*)$/);
      if (match) {
        setSlashFilter(match[1].toLowerCase());
        setShowSlashMenu(true);
        setShowMentionMenu(false);
        return;
      }
    }
    setShowSlashMenu(false);

    // Check for @-mention trigger
    const mentionMatch = val.match(/(?:^|\s)@([a-zA-Z]*)$/);
    if (mentionMatch) {
      setMentionFilter(mentionMatch[1].toLowerCase());
      setShowMentionMenu(true);
      setShowSlashMenu(false);
      return;
    }
    setShowMentionMenu(false);
  };

  // Submit message
  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    if (isRunning) {
      if (onStop) onStop();
      return;
    }

    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;

    // Intercept client-side slash commands
    if (trimmed === "/new") {
      if (onNewThread) onNewThread();
      setText("");
      return;
    }
    if (trimmed === "/settings") {
      if (onOpenSettings) onOpenSettings();
      setText("");
      return;
    }
    if (trimmed === "/tasks" || trimmed === "/memory") {
      if (onOpenAudit) onOpenAudit();
      setText("");
      return;
    }

    if (onSend) {
      let fullMessage = trimmed;
      if (attachments.length > 0) {
        const fileNames = attachments.map((a) => a.name).join(", ");
        fullMessage = `${fullMessage ? fullMessage + "\n\n" : ""}[Attached files: ${fileNames}]`;
      }
      onSend(fullMessage);
    }

    setText("");
    setAttachments([]);
    setShowSlashMenu(false);
    setShowMentionMenu(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === "Escape") {
      setShowSlashMenu(false);
      setShowMentionMenu(false);
    }
  };

  const selectSlashCommand = (cmd) => {
    if (cmd.command === "/new") {
      if (onNewThread) onNewThread();
      setText("");
    } else if (cmd.command === "/settings") {
      if (onOpenSettings) onOpenSettings();
      setText("");
    } else if (cmd.command === "/tasks" || cmd.command === "/memory") {
      if (onOpenAudit) onOpenAudit();
      setText("");
    } else {
      setText(cmd.command + " ");
      textareaRef.current?.focus();
    }
    setShowSlashMenu(false);
  };

  const selectMention = (m) => {
    const updated = text.replace(/@([a-zA-Z]*)$/, `${m.tag} `);
    setText(updated);
    setShowMentionMenu(false);
    textareaRef.current?.focus();
  };

  const processFiles = (fileList) => {
    const newAttachments = [];
    for (const file of fileList) {
      if (file.size > 15 * 1024 * 1024) {
        alert(`File "${file.name}" exceeds 15MB limit.`);
        continue;
      }
      newAttachments.push({
        id: Math.random().toString(36).substring(7),
        name: file.name,
        size: (file.size / 1024).toFixed(1) + " KB",
        type: file.type.startsWith("image/") ? "image" : "document",
      });
    }
    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const handleFileInputChange = (e) => {
    if (e.target.files) {
      processFiles(Array.from(e.target.files));
    }
    e.target.value = "";
  };

  const handlePaste = (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === "file") {
        const file = items[i].getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      processFiles(files);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer?.files) {
      processFiles(Array.from(e.dataTransfer.files));
    }
  };

  const removeAttachment = (id) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const filteredSlash = SLASH_COMMANDS.filter((s) => s.command.slice(1).includes(slashFilter));
  const filteredMentions = MENTIONS.filter(
    (m) => m.tag.slice(1).includes(mentionFilter) || m.label.toLowerCase().includes(mentionFilter)
  );

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`relative mx-auto w-full max-w-3xl rounded-2xl border transition-all ${
        isDragOver
          ? "border-[var(--accent)] bg-[var(--surface-2)] ring-2 ring-[var(--accent-glow)]"
          : "border-[var(--border-2)] bg-[var(--surface)] shadow-lg"
      }`}
    >
      {/* Drag & drop overlay indicator */}
      {isDragOver && (
        <div className="absolute inset-0 z-30 flex items-center justify-center rounded-2xl bg-[var(--surface)]/90 backdrop-blur-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--accent)]">
            <Paperclip className="h-5 w-5 animate-bounce" /> Drop files to attach to Cortex
          </div>
        </div>
      )}

      {/* Slash command popup */}
      {showSlashMenu && filteredSlash.length > 0 && (
        <div className="absolute bottom-full left-0 mb-2 w-72 overflow-hidden rounded-xl border border-[var(--border-2)] bg-[var(--surface)] shadow-2xl backdrop-blur-xl z-30">
          <div className="border-b border-[var(--border)] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
            Cortex Slash Commands
          </div>
          <div className="max-h-56 overflow-y-auto p-1">
            {filteredSlash.map((cmd) => {
              const Icon = cmd.icon;
              return (
                <button
                  key={cmd.command}
                  type="button"
                  onClick={() => selectSlashCommand(cmd)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
                >
                  <Icon className="h-4 w-4 text-[var(--accent)] flex-shrink-0" />
                  <div className="flex-1 truncate">
                    <span className="font-mono font-semibold text-[var(--accent)]">{cmd.command}</span>
                    <span className="ml-2 text-[11px] text-[var(--text-muted)]">{cmd.desc}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Mention popup */}
      {showMentionMenu && filteredMentions.length > 0 && (
        <div className="absolute bottom-full left-0 mb-2 w-72 overflow-hidden rounded-xl border border-[var(--border-2)] bg-[var(--surface)] shadow-2xl backdrop-blur-xl z-30">
          <div className="border-b border-[var(--border)] px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
            Reference Connected Capability
          </div>
          <div className="max-h-56 overflow-y-auto p-1">
            {filteredMentions.map((m) => {
              const Icon = m.icon;
              return (
                <button
                  key={m.tag}
                  type="button"
                  onClick={() => selectMention(m)}
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
                >
                  <Icon className="h-4 w-4 text-[var(--accent-2)] flex-shrink-0" />
                  <div className="flex-1 truncate">
                    <span className="font-mono font-semibold text-[var(--accent-2)]">{m.tag}</span>
                    <span className="ml-2 text-[11px] text-[var(--text-muted)]">{m.label}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Attachment previews */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] p-2.5">
          {attachments.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-xs text-[var(--text)]"
            >
              {a.type === "image" ? (
                <ImageIcon className="h-3.5 w-3.5 text-[var(--accent)]" />
              ) : (
                <FileText className="h-3.5 w-3.5 text-[var(--text-muted)]" />
              )}
              <span className="max-w-[140px] truncate text-[11px] font-medium">{a.name}</span>
              <span className="text-[10px] text-[var(--text-subtle)]">({a.size})</span>
              <button
                type="button"
                onClick={() => removeAttachment(a.id)}
                className="ml-1 text-[var(--text-subtle)] hover:text-[var(--bad)]"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Main Composer Input Form */}
      <form onSubmit={handleSubmit} className="p-3">
        {/* Multiline textarea */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Ask Cortex, plan a workflow, or type '/' for commands..."
          rows={1}
          className="w-full resize-none bg-transparent px-1 text-sm text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none leading-relaxed"
          style={{ minHeight: "26px", maxHeight: "180px" }}
        />

        {/* Action Toolbar */}
        <div className="flex items-center justify-between pt-2 border-t border-[var(--border)] mt-2">
          <div className="flex items-center gap-1">
            {/* Attachment Button with Guaranteed Hidden File Input */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileInputChange}
              multiple
              style={{ display: "none" }}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
              title="Attach File (<15MB)"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            {/* Voice Dictation Button */}
            <button
              type="button"
              onClick={onAudioDictate}
              className={`flex h-8 w-8 items-center justify-center rounded-lg transition-all ${
                isListening
                  ? "bg-[var(--bad)] text-white shadow-md animate-pulse"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
              }`}
              title={isListening ? "Listening… click to finish" : "Voice Dictation"}
            >
              <Mic className="h-4 w-4" />
            </button>

            {/* Command Helper Pills */}
            <div className="hidden sm:flex items-center gap-1.5 ml-2">
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/help" })}
                className="rounded bg-[var(--surface-2)] px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] border border-[var(--border)]"
              >
                /help
              </button>
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/plan" })}
                className="rounded bg-[var(--surface-2)] px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] border border-[var(--border)]"
              >
                /plan
              </button>
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/research" })}
                className="rounded bg-[var(--surface-2)] px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] border border-[var(--border)]"
              >
                /research
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isRunning ? (
              <button
                type="button"
                onClick={onStop}
                className="flex h-8 items-center gap-1.5 rounded-lg bg-[var(--bad)] px-3 text-xs font-semibold text-white hover:opacity-90 shadow-sm transition-all"
              >
                <Square className="h-3.5 w-3.5 fill-current" /> Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!text.trim() && attachments.length === 0}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-sm hover:opacity-90 disabled:opacity-30 disabled:hover:opacity-30 transition-all"
                title="Send Message (Enter)"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
export default CortexComposer;
