import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Send, Square, Paperclip, Mic, MicOff, X,
  FileText, Image as ImageIcon, Sparkles, Terminal,
  Globe, Mail, Calendar, Compass, Shield, Eye, HelpCircle,
  Folder, Sliders, ChevronUp, Bot
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
      setText("");
      if (onNewThread) onNewThread();
      return;
    }
    if (trimmed === "/settings") {
      setText("");
      if (onOpenSettings) onOpenSettings();
      return;
    }
    if (trimmed === "/tasks" || trimmed === "/history") {
      setText("");
      if (onOpenAudit) onOpenAudit();
      return;
    }
    if (trimmed === "/stop") {
      setText("");
      if (onStop) onStop();
      return;
    }

    // Normal submission (including attached file names if any)
    let payloadText = trimmed;
    if (attachments.length > 0) {
      const attachmentSummaries = attachments.map(a => `[Attached file: ${a.name} (${Math.round(a.size / 1024)}KB)]`).join("\n");
      payloadText = payloadText ? `${payloadText}\n\n${attachmentSummaries}` : attachmentSummaries;
    }

    if (onSend) {
      onSend(payloadText);
    }

    setText("");
    setAttachments([]);
    setShowSlashMenu(false);
    setShowMentionMenu(false);
  };

  // Keydown handling: Enter to send, Shift+Enter for newline
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === "Escape") {
      setShowSlashMenu(false);
      setShowMentionMenu(false);
    }
  };

  // Select slash command
  const selectSlashCommand = (cmd) => {
    if (cmd.command === "/new") {
      if (onNewThread) onNewThread();
      setText("");
    } else if (cmd.command === "/settings") {
      if (onOpenSettings) onOpenSettings();
      setText("");
    } else if (cmd.command === "/tasks") {
      if (onOpenAudit) onOpenAudit();
      setText("");
    } else if (cmd.command === "/help") {
      setText("What can Cortex do? Explain your capabilities and available tools.");
    } else if (cmd.command === "/research") {
      setText("Research the latest developments in AI agents and summarize findings with citations.");
    } else if (cmd.command === "/plan") {
      setText("Plan my project work for the next seven days with structured milestones.");
    } else if (cmd.command === "/summarize") {
      setText("Summarize our discussion so far into key takeaways.");
    } else if (cmd.command === "/memory") {
      setText("What do you know about me? Show stored preferences and facts.");
    } else if (cmd.command === "/voice") {
      setText("Explain how voice interaction and multilingual TTS work.");
    } else {
      setText(cmd.command + " ");
    }
    setShowSlashMenu(false);
    if (textareaRef.current) textareaRef.current.focus();
  };

  // Select @-mention
  const selectMention = (mention) => {
    const updated = text.replace(/(?:^|\s)@([a-zA-Z]*)$/, ` ${mention.tag} `);
    setText(updated.trimStart());
    setShowMentionMenu(false);
    if (textareaRef.current) textareaRef.current.focus();
  };

  // File attachments validation (< 15MB)
  const processFiles = (files) => {
    const valid = [];
    const MAX_SIZE = 15 * 1024 * 1024; // 15MB limit
    for (const f of files) {
      if (f.size > MAX_SIZE) {
        alert(`File ${f.name} exceeds 15MB limit.`);
        continue;
      }
      valid.push({
        id: "att-" + Date.now() + "-" + Math.random().toString(36).substr(2, 4),
        name: f.name,
        size: f.size,
        type: f.type,
        file: f,
      });
    }
    setAttachments(prev => [...prev, ...valid]);
  };

  const handleFileInputChange = (e) => {
    if (e.target.files) {
      processFiles(Array.from(e.target.files));
    }
  };

  // Clipboard image pasting
  const handlePaste = (e) => {
    if (e.clipboardData?.items) {
      const files = [];
      for (const item of e.clipboardData.items) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length > 0) {
        processFiles(files);
      }
    }
  };

  // Drag-and-drop
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
    setAttachments(prev => prev.filter(a => a.id !== id));
  };

  const filteredSlash = SLASH_COMMANDS.filter(s => s.command.slice(1).includes(slashFilter));
  const filteredMentions = MENTIONS.filter(m => m.tag.slice(1).includes(mentionFilter) || m.label.toLowerCase().includes(mentionFilter));

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`relative mx-auto w-full max-w-3xl rounded-2xl border transition-all ${
        isDragOver
          ? "border-sky-400 bg-sky-950/40 ring-2 ring-sky-400/50"
          : "border-white/10 bg-black/40 shadow-2xl backdrop-blur-xl"
      }`}
    >
      {/* Drag & drop overlay indicator */}
      {isDragOver && (
        <div className="absolute inset-0 z-30 flex items-center justify-center rounded-2xl bg-sky-950/80 backdrop-blur-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-sky-200">
            <Paperclip className="h-5 w-5 animate-bounce" /> Drop files to attach to Cortex
          </div>
        </div>
      )}

      {/* Slash command popup */}
      {showSlashMenu && filteredSlash.length > 0 && (
        <div className="absolute bottom-full left-0 mb-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 shadow-2xl backdrop-blur-xl z-20">
          <div className="border-b border-white/5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
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
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-200 hover:bg-white/10 transition-colors"
                >
                  <Icon className="h-4 w-4 text-sky-400 flex-shrink-0" />
                  <div className="flex-1 truncate">
                    <span className="font-mono font-semibold text-sky-300">{cmd.command}</span>
                    <span className="ml-2 text-[11px] text-slate-400">{cmd.desc}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Mention popup */}
      {showMentionMenu && filteredMentions.length > 0 && (
        <div className="absolute bottom-full left-0 mb-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 shadow-2xl backdrop-blur-xl z-20">
          <div className="border-b border-white/5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
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
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-200 hover:bg-white/10 transition-colors"
                >
                  <Icon className="h-4 w-4 text-purple-400 flex-shrink-0" />
                  <div className="flex-1 truncate">
                    <span className="font-mono font-semibold text-purple-300">{m.tag}</span>
                    <span className="ml-2 text-[11px] text-slate-400">{m.label}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Attachment previews */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 p-3 border-b border-white/5">
          {attachments.map((att) => (
            <div
              key={att.id}
              className="group flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-200"
            >
              {att.type.startsWith("image/") ? (
                <ImageIcon className="h-3.5 w-3.5 text-sky-400" />
              ) : (
                <FileText className="h-3.5 w-3.5 text-slate-400" />
              )}
              <span className="max-w-[120px] truncate text-[11px]">{att.name}</span>
              <button
                type="button"
                onClick={() => removeAttachment(att.id)}
                className="ml-1 rounded-full p-0.5 text-slate-400 hover:bg-white/10 hover:text-white"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input area */}
      <form onSubmit={handleSubmit} className="flex flex-col p-2.5">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          rows={1}
          placeholder="Ask Cortex, type '/' for commands, or '@' to tag tools…"
          className="w-full resize-none bg-transparent px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none leading-relaxed"
        />

        {/* Action bar bottom */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-1">
            {/* Attachment Button */}
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileInputChange}
              multiple
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-white/10 hover:text-slate-200 transition-colors"
              title="Attach File"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            {/* Voice Dictation Button */}
            <button
              type="button"
              onClick={onAudioDictate}
              className={`flex h-8 w-8 items-center justify-center rounded-lg transition-all ${
                isListening
                  ? "bg-rose-500 text-white shadow-md shadow-rose-500/30 animate-pulse"
                  : "text-slate-400 hover:bg-white/10 hover:text-slate-200"
              }`}
              title={isListening ? "Listening… click to send" : "Voice Dictation"}
            >
              {isListening ? <Mic className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>

            {/* Command Helper Pills */}
            <div className="hidden sm:flex items-center gap-1.5 ml-2">
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/help" })}
                className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-slate-400 hover:bg-white/10 hover:text-slate-200"
              >
                /help
              </button>
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/plan" })}
                className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-slate-400 hover:bg-white/10 hover:text-slate-200"
              >
                /plan
              </button>
              <button
                type="button"
                onClick={() => selectSlashCommand({ command: "/research" })}
                className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-slate-400 hover:bg-white/10 hover:text-slate-200"
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
                className="flex h-8 items-center gap-1.5 rounded-lg bg-rose-600 px-3 text-xs font-semibold text-white hover:bg-rose-500 shadow-md transition-all"
              >
                <Square className="h-3.5 w-3.5 fill-current" /> Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!text.trim() && attachments.length === 0}
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-md hover:bg-indigo-500 disabled:opacity-30 disabled:hover:bg-indigo-600 transition-all"
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

