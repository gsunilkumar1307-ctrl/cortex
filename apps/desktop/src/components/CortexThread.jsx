import React, { useRef, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import {
  Sparkles, User, Copy, Check, Volume2, RotateCcw,
  Edit2, ChevronLeft, ChevronRight, ArrowDown, ExternalLink,
  Bot, Clock, AlertTriangle, Play, Square
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
  const renderCodeBlock = ({ node, inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || "");
    const codeString = String(children).replace(/\n$/, "");

    if (!inline && match) {
      return (
        <div className="relative my-3 overflow-hidden rounded-xl border border-white/10 bg-black/50 shadow-md">
          <div className="flex items-center justify-between border-b border-white/5 bg-slate-900/60 px-3.5 py-1.5 text-[11px] text-slate-400">
            <span className="font-mono text-indigo-300 font-semibold">{match[1]}</span>
            <button
              type="button"
              onClick={() => copyToClipboard(codeString, codeString)}
              className="flex items-center gap-1 rounded px-2 py-0.5 hover:bg-white/10 text-slate-300 hover:text-white"
            >
              {copiedId === codeString ? (
                <>
                  <Check className="h-3 w-3 text-emerald-400" />
                  <span className="text-[10px] text-emerald-400">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  <span className="text-[10px]">Copy</span>
                </>
              )}
            </button>
          </div>
          <SyntaxHighlighter
            style={vscDarkPlus}
            language={match[1]}
            PreTag="div"
            customStyle={{
              margin: 0,
              padding: "1rem",
              background: "transparent",
              fontSize: "12px",
              lineHeight: "1.5",
            }}
            {...props}
          >
            {codeString}
          </SyntaxHighlighter>
        </div>
      );
    }
    return (
      <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs text-indigo-200" {...props}>
        {children}
      </code>
    );
  };

  // Helper to extract plain text from message content
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

  return (
    <div
      ref={viewportRef}
      onScroll={handleScroll}
      className="relative flex-1 overflow-y-auto px-4 py-6 md:px-8 space-y-6"
    >
      {/* Empty State */}
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center min-h-[60vh] max-w-xl mx-auto text-center space-y-6 select-none animate-in fade-in duration-500">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-tr from-indigo-600 to-sky-400 shadow-xl shadow-indigo-500/20">
            <Sparkles className="h-8 w-8 text-white" />
          </div>

          <div className="space-y-2">
            <h2 className="text-xl font-bold tracking-tight text-slate-100">
              Cortex Desktop Assistant
            </h2>
            <p className="text-xs text-slate-400 leading-relaxed max-w-md">
              Supervised autonomous companion for macOS. Controls Apple Mail, Safari, Finder, Notes, and desktop workflows with cryptographic approval gates.
            </p>
          </div>

          {/* Starter Suggestions */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full pt-4">
            {[
              {
                title: "Draft an Email",
                desc: "Draft an email to Rahul explaining I'll be 15 minutes late",
                prompt: "Draft an email to Rahul explaining that I will be late for our sync.",
              },
              {
                title: "Plan 7-Day Project",
                desc: "Decompose a 7-day milestones roadmap",
                prompt: "Plan my project work for the next seven days with milestones.",
              },
              {
                title: "Evidence Web Research",
                desc: "Search latest autonomous AI agent papers",
                prompt: "Research the latest developments in AI agents and provide citations.",
              },
              {
                title: "ಕನ್ನಡದಲ್ಲಿ ಸಂಭಾಷಣೆ",
                desc: "ನನ್ನ ಕೆಲಸಗಳನ್ನು ಪ್ಲಾನ್ ಮಾಡು",
                prompt: "ನನಗೆ ಇವತ್ತಿನ ಕೆಲಸಗಳನ್ನು ಪ್ಲಾನ್ ಮಾಡು.",
              },
            ].map((item, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectPrompt && onSelectPrompt(item.prompt)}
                className="flex flex-col text-left rounded-xl border border-white/5 bg-white/5 p-3.5 hover:border-indigo-500/40 hover:bg-indigo-950/20 transition-all group"
              >
                <span className="text-xs font-semibold text-slate-200 group-hover:text-indigo-300">
                  {item.title}
                </span>
                <span className="text-[11px] text-slate-400 mt-1 line-clamp-2">
                  {item.desc}
                </span>
              </button>
            ))}
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
            <div className="flex items-center gap-2 px-1 text-[11px] text-slate-500 font-medium">
              {isUser ? (
                <>
                  <span>You</span>
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-700 text-slate-300">
                    <User className="h-3 w-3" />
                  </div>
                </>
              ) : (
                <>
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white shadow-sm">
                    <Bot className="h-3 w-3" />
                  </div>
                  <span className="text-indigo-400 font-semibold">Cortex</span>
                  {task?.language && task.language !== "en" && (
                    <span className="rounded bg-indigo-500/10 px-1 py-0.2 text-[9px] uppercase font-mono text-indigo-300">
                      {task.language}
                    </span>
                  )}
                </>
              )}
            </div>

            {/* Message Bubble / Editor */}
            {isEditing ? (
              <div className="w-full rounded-2xl border border-indigo-500/40 bg-indigo-950/40 p-3 space-y-2">
                <textarea
                  value={editInputText}
                  onChange={(e) => setEditInputText(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-lg bg-black/40 p-2 text-xs text-white border border-white/10 focus:border-indigo-400 focus:outline-none"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingMessageId(null)}
                    className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSaveEdit(msg.id)}
                    className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-500"
                  >
                    Update & Resend
                  </button>
                </div>
              </div>
            ) : (
              <div
                className={`group relative rounded-2xl px-4 py-3 text-sm leading-relaxed transition-all ${
                  isUser
                    ? "bg-indigo-600 text-white shadow-md rounded-tr-sm max-w-[85%]"
                    : "bg-slate-900/80 border border-white/10 text-slate-100 shadow-lg rounded-tl-sm w-full backdrop-blur-md"
                }`}
              >
                {/* Text Content with Markdown */}
                {isUser ? (
                  <div className="whitespace-pre-wrap break-words">{textContent}</div>
                ) : (
                  <div className="prose prose-invert max-w-none text-xs sm:text-sm prose-p:leading-relaxed prose-headings:font-bold prose-a:text-indigo-400 hover:prose-a:underline prose-table:my-2 prose-th:border prose-th:border-white/10 prose-th:p-2 prose-td:border prose-td:border-white/10 prose-td:p-2">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code: renderCodeBlock,
                        table: ({ children }) => (
                          <div className="overflow-x-auto my-3 rounded-lg border border-white/10">
                            <table className="w-full text-left text-xs border-collapse">{children}</table>
                          </div>
                        ),
                      }}
                    >
                      {textContent}
                    </ReactMarkdown>

                    {/* Generative UI Components */}
                    {task && (
                      <div className="pt-2 space-y-3 not-prose">
                        {/* 1. Apple Mail Draft */}
                        {(task.command === "send_mail" || task.command === "email" || task.intent?.includes("email") || task.intent?.includes("draft")) && (
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
                  className={`mt-2 flex items-center gap-1.5 pt-1.5 border-t border-white/5 text-[11px] text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity ${
                    isUser ? "justify-end" : "justify-start"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => copyToClipboard(textContent, msg.id)}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 hover:text-white transition-colors"
                    title="Copy message"
                  >
                    {copiedId === msg.id ? (
                      <Check className="h-3 w-3 text-emerald-400" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                  </button>

                  {isUser && (
                    <button
                      type="button"
                      onClick={() => handleStartEdit(msg)}
                      className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 hover:text-white transition-colors"
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
                        className={`flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 transition-colors ${
                          isSpeaking ? "text-indigo-400 animate-pulse" : "hover:text-white"
                        }`}
                        title={isSpeaking ? "Stop Speaking" : "Read Aloud"}
                      >
                        {isSpeaking ? <Square className="h-3 w-3 fill-current" /> : <Volume2 className="h-3 w-3" />}
                      </button>

                      <button
                        type="button"
                        onClick={onReload}
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 hover:text-white transition-colors"
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
          className="fixed bottom-24 right-8 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-indigo-600 text-white shadow-xl hover:bg-indigo-500 transition-all"
          title="Scroll to latest"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
export default CortexThread;

