import React, { useState } from "react";
import {
  Plus, Search, MessageSquare, Trash2, Edit2, Check, X,
  Shield, Sliders, History, Activity, Download, Terminal,
  Compass, ChevronLeft, ChevronRight, Sparkles, Wrench
} from "lucide-react";

export function CortexSidebar({
  threads = [],
  activeThreadId,
  onSelectThread,
  onNewThread,
  onDeleteThread,
  onRenameThread,
  onOpenSettings,
  onOpenAudit,
  onExportMarkdown,
  isCollapsed,
  onToggleCollapse,
}) {
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  const filteredThreads = threads.filter((t) => {
    const q = search.toLowerCase();
    return (t.title || "").toLowerCase().includes(q) || (t.preview || "").toLowerCase().includes(q);
  });

  const startRename = (t, e) => {
    e.stopPropagation();
    setEditingId(t.id);
    setEditTitle(t.title || "Conversation");
  };

  const handleSaveRename = (id, e) => {
    e.stopPropagation();
    if (editTitle.trim() && onRenameThread) {
      onRenameThread(id, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleDelete = (id, e) => {
    e.stopPropagation();
    if (confirmDeleteId === id) {
      if (onDeleteThread) onDeleteThread(id);
      setConfirmDeleteId(null);
    } else {
      setConfirmDeleteId(id);
    }
  };

  if (isCollapsed) {
    return (
      <aside className="flex h-full w-14 flex-shrink-0 flex-col items-center justify-between border-r border-[var(--border)] bg-[var(--surface)] py-3 backdrop-blur-xl z-20">
        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={onToggleCollapse}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
            title="Expand Sidebar"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onNewThread}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-sm hover:opacity-90 transition-opacity"
            title="New Chat (⌘N)"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={onOpenAudit}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
            title="Task Activity"
          >
            <Activity className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
            title="Settings & Memory"
          >
            <Sliders className="h-4 w-4" />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-64 flex-shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] backdrop-blur-xl transition-all select-none z-20">
      {/* Brand Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-sm shadow-[var(--accent-glow)]">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-bold tracking-wider text-[var(--text)] uppercase">CORTEX</div>
            <div className="text-[10px] text-[var(--text-muted)]">Autonomous Assistant</div>
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleCollapse}
          className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
          title="Collapse Sidebar"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
      </div>

      {/* New Conversation Button */}
      <div className="p-3">
        <button
          type="button"
          onClick={onNewThread}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-[var(--border-2)] bg-[var(--surface-2)] px-3 py-2 text-xs font-semibold text-[var(--text)] hover:bg-[var(--surface-hover)] hover:border-[var(--accent)] transition-all shadow-sm"
        >
          <Plus className="h-4 w-4 text-[var(--accent)]" /> New Conversation
        </button>
      </div>

      {/* Search Input */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 text-xs text-[var(--text)]">
          <Search className="h-3.5 w-3.5 text-[var(--text-subtle)]" />
          <input
            type="text"
            placeholder="Search threads…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none"
          />
        </div>
      </div>

      {/* Thread List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
          Conversations ({filteredThreads.length})
        </div>

        {filteredThreads.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-[var(--text-muted)]">
            {search ? "No matching threads" : "No previous conversations"}
          </div>
        ) : (
          filteredThreads.map((t) => {
            const isActive = t.id === activeThreadId;
            const isEditing = editingId === t.id;
            const isConfirming = confirmDeleteId === t.id;

            return (
              <div
                key={t.id}
                onClick={() => !isEditing && onSelectThread(t.id)}
                className={`group relative flex items-center justify-between rounded-xl px-2.5 py-2 text-xs cursor-pointer transition-all ${
                  isActive
                    ? "bg-[var(--surface-2)] border border-[var(--border-2)] text-[var(--text)] shadow-sm font-medium"
                    : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <MessageSquare className={`h-3.5 w-3.5 flex-shrink-0 ${isActive ? "text-[var(--accent)]" : "text-[var(--text-subtle)]"}`} />
                  {isEditing ? (
                    <input
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSaveRename(t.id, e);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      autoFocus
                      className="w-full rounded bg-[var(--surface)] px-1 py-0.5 text-xs text-[var(--text)] border border-[var(--accent)] focus:outline-none"
                    />
                  ) : (
                    <div className="truncate">
                      <div className="truncate text-[12px]">{t.title || "Untitled"}</div>
                      {t.preview && (
                        <div className="truncate text-[10px] text-[var(--text-subtle)]">{t.preview}</div>
                      )}
                    </div>
                  )}
                </div>

                {/* Actions: Rename / Delete */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {isEditing ? (
                    <button
                      type="button"
                      onClick={(e) => handleSaveRename(t.id, e)}
                      className="p-1 text-[var(--good)] hover:opacity-80"
                      title="Save"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={(e) => startRename(t, e)}
                        className="p-1 text-[var(--text-subtle)] hover:text-[var(--text)]"
                        title="Rename"
                      >
                        <Edit2 className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDelete(t.id, e)}
                        className={`p-1 ${isConfirming ? "text-[var(--bad)]" : "text-[var(--text-subtle)] hover:text-[var(--bad)]"}`}
                        title={isConfirming ? "Click again to confirm delete" : "Delete conversation"}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Connected Tools & Capabilities Status */}
      <div className="px-3 py-2 border-t border-[var(--border)]">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)] mb-1.5 flex items-center gap-1">
          <Wrench className="h-3 w-3" /> Connected Tools
        </div>
        <div className="flex flex-wrap gap-1">
          {["Apple Mail", "Safari", "Finder", "Screen Vision"].map((tool) => (
            <span key={tool} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded bg-[var(--surface-2)] text-[var(--text-muted)] border border-[var(--border)]">
              {tool}
            </span>
          ))}
        </div>
      </div>

      {/* Footer Navigation */}
      <div className="border-t border-[var(--border)] p-2 space-y-1">
        <button
          type="button"
          onClick={onExportMarkdown}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
        >
          <Download className="h-4 w-4 text-[var(--text-subtle)]" /> Export to Markdown
        </button>

        <button
          type="button"
          onClick={onOpenAudit}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
        >
          <Activity className="h-4 w-4 text-[var(--text-subtle)]" /> Tasks & Audit Trail
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors"
        >
          <Sliders className="h-4 w-4 text-[var(--text-subtle)]" /> Settings & Memory
        </button>
      </div>
    </aside>
  );
}
export default CortexSidebar;
