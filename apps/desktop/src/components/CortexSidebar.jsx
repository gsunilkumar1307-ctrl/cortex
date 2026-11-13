import React, { useState } from "react";
import {
  Plus, Search, MessageSquare, Trash2, Edit2, Check, X,
  Shield, Sliders, History, Activity, Download, Terminal,
  Compass, ChevronLeft, ChevronRight, Sparkles
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
      <div className="flex h-full w-14 flex-col items-center justify-between border-r border-white/10 bg-black/40 py-3 backdrop-blur-xl">
        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={onToggleCollapse}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600/30 text-indigo-400 hover:bg-indigo-600/50"
            title="Expand Sidebar"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onNewThread}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white"
            title="New Chat"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={onOpenAudit}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-white/10 hover:text-white"
            title="Task Activity"
          >
            <Activity className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-white/10 hover:text-white"
            title="Settings"
          >
            <Sliders className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <aside className="flex h-full w-64 flex-col border-r border-white/10 bg-black/50 backdrop-blur-xl transition-all select-none">
      {/* Brand Header */}
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-md shadow-indigo-600/30">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-bold tracking-wider text-slate-100 uppercase">CORTEX</div>
            <div className="text-[10px] text-slate-400">Autonomous Assistant</div>
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleCollapse}
          className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white"
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
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-indigo-600/20 px-3 py-2 text-xs font-semibold text-indigo-200 hover:bg-indigo-600/30 hover:border-indigo-500/40 transition-all shadow-sm"
        >
          <Plus className="h-4 w-4" /> New Conversation
        </button>
      </div>

      {/* Search Input */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-lg border border-white/5 bg-white/5 px-2.5 py-1.5 text-xs text-slate-300">
          <Search className="h-3.5 w-3.5 text-slate-500" />
          <input
            type="text"
            placeholder="Search threads…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent text-xs text-slate-200 placeholder-slate-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Thread List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          History ({filteredThreads.length})
        </div>

        {filteredThreads.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-slate-500">
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
                    ? "bg-indigo-600/25 border border-indigo-500/30 text-white"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <MessageSquare className={`h-3.5 w-3.5 flex-shrink-0 ${isActive ? "text-indigo-400" : "text-slate-500"}`} />
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
                      className="w-full rounded bg-black/60 px-1 py-0.5 text-xs text-white border border-indigo-400 focus:outline-none"
                    />
                  ) : (
                    <div className="truncate">
                      <div className="truncate font-medium text-[12px]">{t.title || "Untitled"}</div>
                      {t.preview && (
                        <div className="truncate text-[10px] text-slate-400">{t.preview}</div>
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
                      className="p-1 text-emerald-400 hover:text-emerald-300"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={(e) => startRename(t, e)}
                        className="p-1 text-slate-400 hover:text-white"
                        title="Rename"
                      >
                        <Edit2 className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDelete(t.id, e)}
                        className={`p-1 ${isConfirming ? "text-rose-400" : "text-slate-400 hover:text-rose-400"}`}
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

      {/* Footer Navigation */}
      <div className="border-t border-white/5 p-2 space-y-1">
        <button
          type="button"
          onClick={onExportMarkdown}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
        >
          <Download className="h-4 w-4 text-slate-400" /> Export to Markdown
        </button>

        <button
          type="button"
          onClick={onOpenAudit}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
        >
          <Activity className="h-4 w-4 text-slate-400" /> Tasks & Audit Trail
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
        >
          <Sliders className="h-4 w-4 text-slate-400" /> Settings & Memory
        </button>
      </div>
    </aside>
  );
}
export default CortexSidebar;

