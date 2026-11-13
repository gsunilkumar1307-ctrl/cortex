import React, { useRef, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus, prism } from "react-syntax-highlighter/dist/esm/styles/prism";
import {
  Sparkles, User, Copy, Check, Volume2, RotateCcw,
  Edit2, ArrowDown, Bot, Square, Mail, Compass, Calendar, Monitor, FileText
} from "lucide-react";

import MailDraftCard from "./tools/MailDraftCard";
import TaskPlanCard from "./tools/TaskPlanCard";
import WebResearchCard from "./tools/WebResearchCard";
import DesktopActionCard from "./tools/DesktopActionCard";
import ScreenVisionCard from "./tools/ScreenVisionCard";
import ApprovalCard from "./tools/ApprovalCard";
import ToolErrorCard from "./tools/ToolErrorCard";

export function CortexThread({
  messages = [],
  isRunning = false,
  onEditMessage,
  onReload,
  onApproveTask,
  onCancelTask,
  onEditDraft,
  onSelectPrompt,
  onSpeakText,
  isSpeaking,
  onStopSpeech,
  theme = "dark",
}) {
  const viewportRef = useRef(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [editInputText, setEditInputText] = useState("");

  // Auto-scroll on new messages or during streaming
  useEffect(() => {
    if (viewportRef.current) {
      const { scrollHeight, scrollTop, clientHeight } = viewportRef.current;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 160;
      if (isNearBottom || isRunning) {
        viewportRef.current.scrollTo({
          top: scrollHeight,
          behavior: isRunning ? "auto" : "smooth",
        });
      }
    }
  }, [messages, isRunning]);

  // Track scroll position to show "Jump to bottom" button
  const handleScroll = () => {
    if (!viewportRef.current) return;
    const { scrollHeight, scrollTop, clientHeight } = viewportRef.current;
    setShowScrollBottom(scrollHeight - scrollTop - clientHeight > 180);
  };

  const scrollToBottom = () => {
    if (viewportRef.current) {
      viewportRef.current.scrollTo({
        top: viewportRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  };

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleStartEdit = (msg) => {
    setEditingMessageId(msg.id);
    let str = "";
    if (Array.isArray(msg.content)) {
      for (const part of msg.content) {
        if (part.type === "text") str += part.text;
      }
    } else if (typeof msg.content === "string") {
      str = msg.content;
    }
    setEditInputText(str);
  };

  const handleSaveEdit = (msgId) => {
    if (onEditMessage && editInputText.trim()) {
      onEditMessage({ id: msgId, content: [{ type: "text", text: editInputText.trim() }] });
    }
    setEditingMessageId(null);
  };

  // Render markdown code blocks with copy button
  const renderCodeBlock = ({ inline, className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const codeString = String(children).replace(/\n$/, "");

    if (!inline && match) {
      return (
        <div className="relative my-3 overflow-hidden rounded-xl border border-[var(--border-2)] bg-[var(--surface-2)]">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-1.5 text-[11px] font-mono text-[var(--text-muted)]">
            <span className="uppercase tracking-wide">{match[1]}</span>
            <button
              type="button"
              onClick={() => copyToClipboard(codeString, codeString)}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
            >
              {copiedId === codeString ? (
                <>
                  <Check className="h-3 w-3 text-[var(--good)]" />
                  <span className="text-[10px] text-[var(--good)]">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  <span className="text-[10px]">Copy</span>
                </>
              )}
            </button>
          </div>
          <div className="p-3 text-xs overflow-x-auto font-mono">
            <SyntaxHighlighter
              style={theme === "light" ? prism : vscDarkPlus}
              language={match[1]}
              PreTag="div"
              customStyle={{
                margin: 0,
                background: "transparent",
                padding: 0,
                fontSize: "12px",
              }}
            >
              {codeString}
            </SyntaxHighlighter>
          </div>
        </div>
      );
    }

    return (
      <code className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-xs text-[var(--accent)] border border-[var(--border)]">
        {children}
      </code>
    );
  };

  const getMessageText = (msg) => {
    if (typeof msg.content === "string") return msg.content;
    if (Array.isArray(msg.content)) {
      return msg.content
        .filter((c) => c.type === "text")
        .map((c) => c.text)
        .join("\n");
    }
    return "";
  };

  const WELCOME_SUGGESTIONS = [
    {
      title: "Draft an email",
      desc: "Prepare a concise status update in Apple Mail",
      icon: Mail,
      prompt: "Draft an email to Rahul explaining that I will be late for our sync.",
    },
    {
      title: "Research a topic",
      desc: "Gather evidence and verified citations from the web",
      icon: Compass,
      prompt: "Research the latest developments in AI agents and provide citations.",
    },
    {
      title: "Plan my day",
      desc: "Decompose a multi-step project plan with dependencies",
      icon: Calendar,
      prompt: "Plan my project tasks for today with clear step dependencies.",
    },
    {
      title: "Control desktop applications",
      desc: "Inspect active app windows, files in Finder, or notes",
      icon: Monitor,
      prompt: "Inspect my active desktop window and summarize what is visible.",
    },
    {
      title: "Summarize a document",
      desc: "Extract key takeaways and actionable action items",
      icon: FileText,
      prompt: "Summarize the key architectural decisions of Cortex Agent.",
    },
  ];

  return (
    <div
      ref={viewportRef}
      onScroll={handleScroll}
      className="relative flex-1 overflow-y-auto px-4 py-6 md:px-8 space-y-6"
    >
      {/* Empty Welcome State */}
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center min-h-[60vh] max-w-2xl mx-auto text-center space-y-6 select-none animate-in fade-in duration-500 py-6">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-xl shadow-[var(--accent-glow)]">
            <Sparkles className="h-7 w-7" />
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-bold tracking-tight text-[var(--text)]">
              Welcome to Cortex
            </h2>
            <p className="text-xs text-[var(--text-muted)] leading-relaxed max-w-md mx-auto">
              Your autonomous desktop companion for macOS. Controls Apple Mail, Safari, Finder, and desktop workflows with cryptographic approval gates.
            </p>
          </div>

          {/* 5 Suggested Task Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5 w-full pt-2">
            {WELCOME_SUGGESTIONS.map((item, idx) => {
              const Icon = item.icon;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectPrompt && onSelectPrompt(item.prompt)}
                  className={`flex flex-col text-left rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3.5 hover:border-[var(--accent)] hover:bg-[var(--surface-hover)] transition-all group shadow-sm ${
                    idx === 4 ? "sm:col-span-2 lg:col-span-1" : ""
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <Icon className="h-4 w-4 text-[var(--accent)] group-hover:scale-110 transition-transform" />
                    <span className="text-xs font-semibold text-[var(--text)] group-hover:text-[var(--accent)]">
                      {item.title}
                    </span>
                  </div>
                  <span className="text-[11px] text-[var(--text-muted)] line-clamp-2 leading-snug">
                    {item.desc}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Messages */}
      {messages.map((msg, idx) => {
        const isUser = msg.role === "user";
        const textContent = getMessageText(msg);
        const task = msg.task;
        const isEditing = editingMessageId === msg.id;

        return (
          <div
            key={msg.id || idx}
            className={`flex flex-col max-w-3xl mx-auto ${
              isUser ? "items-end" : "items-start"
            } space-y-2`}
          >
            {/* Header info (avatar, role, timestamp) */}
            <div className="flex items-center gap-2 px-1 text-[11px] text-[var(--text-subtle)] font-medium">
              {isUser ? (
                <>
                  <span>You</span>
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--surface-2)] text-[var(--text)]">
                    <User className="h-3 w-3" />
                  </div>
                </>
              ) : (
                <>
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--accent)] text-white shadow-sm">
                    <Bot className="h-3 w-3" />
                  </div>
                  <span className="text-[var(--accent)] font-semibold">Cortex</span>
                  {task?.language && task.language !== "en" && (
                    <span className="rounded bg-[var(--surface-2)] px-1.5 py-0.2 text-[9px] uppercase font-mono text-[var(--accent)] border border-[var(--border)]">
                      {task.language}
                    </span>
                  )}
                </>
              )}
            </div>

            {/* Message Bubble / Editor */}
            {isEditing ? (
              <div className="w-full rounded-2xl border border-[var(--accent)] bg-[var(--surface)] p-3 space-y-2 shadow-sm">
                <textarea
                  value={editInputText}
                  onChange={(e) => setEditInputText(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-lg bg-[var(--surface-2)] p-2 text-xs text-[var(--text)] border border-[var(--border)] focus:border-[var(--accent)] focus:outline-none"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingMessageId(null)}
                    className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)]"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSaveEdit(msg.id)}
                    className="rounded-md bg-[var(--accent)] px-3 py-1 text-xs font-semibold text-white hover:opacity-90"
                  >
                    Update & Resend
                  </button>
                </div>
              </div>
            ) : (
              <div
                className={`group relative rounded-2xl px-4 py-3 text-sm leading-relaxed transition-all ${
                  isUser
                    ? "bg-[var(--surface-2)] text-[var(--text)] border border-[var(--border-2)] shadow-sm rounded-tr-sm max-w-[85%]"
                    : "bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] shadow-sm rounded-tl-sm w-full backdrop-blur-md"
                }`}
              >
                {/* Text Content with Markdown */}
                {isUser ? (
                  <div className="whitespace-pre-wrap break-words">{textContent}</div>
                ) : (
                  <div className="text-xs sm:text-sm leading-relaxed text-[var(--text)] space-y-2">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code: renderCodeBlock,
                        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
                        h1: ({ children }) => <h1 className="text-base font-bold my-2 text-[var(--text)]">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-sm font-bold my-1.5 text-[var(--text)]">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-xs font-bold my-1 text-[var(--text)]">{children}</h3>,
                        ul: ({ children }) => <ul className="list-disc pl-5 my-1.5 space-y-1">{children}</ul>,
                        ol: ({ children }) => <ol className="list-decimal pl-5 my-1.5 space-y-1">{children}</ol>,
                        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                        blockquote: ({ children }) => (
                          <blockquote className="border-l-2 border-[var(--accent)] pl-3 my-2 italic text-[var(--text-muted)]">
                            {children}
                          </blockquote>
                        ),
                        a: ({ href, children }) => (
                          <a href={href} target="_blank" rel="noopener noreferrer" className="text-[var(--accent)] underline hover:opacity-80">
                            {children}
                          </a>
                        ),
                        table: ({ children }) => (
                          <div className="overflow-x-auto my-3 rounded-lg border border-[var(--border)]">
                            <table className="w-full text-left text-xs border-collapse divide-y divide-[var(--border)]">{children}</table>
                          </div>
                        ),
                        th: ({ children }) => (
                          <th className="p-2 font-semibold bg-[var(--surface-2)] text-[var(--text)]">{children}</th>
                        ),
                        td: ({ children }) => (
                          <td className="p-2 border-t border-[var(--border)] text-[var(--text-muted)]">{children}</td>
                        ),
                      }}
                    >
                      {textContent}
                    </ReactMarkdown>

                    {/* Generative UI Components */}
                    {task && (
                      <div className="pt-2 space-y-3">
                        {/* 1. Apple Mail Draft */}
                        {(task.command === "draft_mail" || task.command === "send_mail" || task.command === "email" || task.command?.includes("mail") || task.intent?.toLowerCase().includes("email") || task.intent?.toLowerCase().includes("draft")) && (
                          <MailDraftCard
                            task={task}
                            onApprove={onApproveTask}
                            onCancel={onCancelTask}
                            onEditDraft={onEditDraft}
                          />
                        )}

                        {/* 2. Structured Multi-Step Plan */}
                        {(task.plan || task.intent?.includes("plan") || task.params?.plan) && (
                          <TaskPlanCard
                            task={task}
                            onCancel={onCancelTask}
                          />
                        )}

                        {/* 3. Evidence-Based Web Research */}
                        {(task.command === "web_search" || task.intent?.includes("search") || task.params?.results || task.params?.citations) && (
                          <WebResearchCard
                            data={task.params || task}
                          />
                        )}

                        {/* 4. Desktop Automation Actions */}
                        {(task.command === "open_app" || task.command === "focus_app" || task.command === "finder_inspect" || task.command === "menu_item") && (
                          <DesktopActionCard
                            task={task}
                          />
                        )}

                        {/* 5. Screen Vision & Accessibility Intelligence */}
                        {(task.command === "screen_vision" || task.command === "observe_screen") && (
                          <ScreenVisionCard
                            data={task.params || task}
                          />
                        )}

                        {/* 6. Human Approval Gate */}
                        {task.requiresApproval && task.status === "waiting_approval" && task.command !== "send_mail" && (
                          <ApprovalCard
                            actionDetails={{
                              id: task.id,
                              action: task.intent || task.command,
                              target: task.params?.app || task.params?.target || "macOS System",
                              parameters: task.params,
                              consequences: task.consequences || "Executes a privileged system action.",
                              approval_hash: task.params?.approval_hash,
                              status: task.status,
                            }}
                            onApprove={onApproveTask}
                            onDeny={onCancelTask}
                          />
                        )}

                        {/* 7. Error & Recovery Card */}
                        {task.status === "failed" && (
                          <ToolErrorCard
                            error={task.error || task.result}
                            onRetry={onReload}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Action Bar (Copy, Edit, TTS, Reload) */}
                <div
                  className={`mt-2 flex items-center gap-1.5 pt-1.5 border-t border-[var(--border)] text-[11px] text-[var(--text-subtle)] opacity-0 group-hover:opacity-100 transition-opacity ${
                    isUser ? "justify-end" : "justify-start"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => copyToClipboard(textContent, msg.id)}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
                    title="Copy message"
                  >
                    {copiedId === msg.id ? (
                      <Check className="h-3 w-3 text-[var(--good)]" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                  </button>

                  {isUser && (
                    <button
                      type="button"
                      onClick={() => handleStartEdit(msg)}
                      className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
                      title="Edit question"
                    >
                      <Edit2 className="h-3 w-3" />
                    </button>
                  )}

                  {!isUser && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          if (isSpeaking) {
                            if (onStopSpeech) onStopSpeech();
                          } else {
                            if (onSpeakText) onSpeakText(textContent, task?.language || "en");
                          }
                        }}
                        className={`flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[var(--surface-hover)] transition-colors ${
                          isSpeaking ? "text-[var(--accent)] animate-pulse" : "hover:text-[var(--text)]"
                        }`}
                        title={isSpeaking ? "Stop Speaking" : "Read Aloud"}
                      >
                        {isSpeaking ? <Square className="h-3 w-3 fill-current" /> : <Volume2 className="h-3 w-3" />}
                      </button>

                      <button
                        type="button"
                        onClick={onReload}
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
                        title="Regenerate response"
                      >
                        <RotateCcw className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Floating Jump-to-bottom button */}
      {showScrollBottom && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="fixed bottom-24 right-8 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-[var(--accent)] text-white shadow-xl hover:opacity-90 transition-all"
          title="Scroll to latest"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
export default CortexThread;
