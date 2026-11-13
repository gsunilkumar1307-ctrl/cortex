import React, { useState, useEffect } from "react";
import { X, Activity, Shield, CheckCircle2, XCircle, Clock, RefreshCw, Lock } from "lucide-react";
import cortexApi from "../../runtime/cortexApi";

export function AuditModal({ isOpen, onClose }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    if (isOpen) {
      loadAudit();
    }
  }, [isOpen]);

  const loadAudit = async () => {
    setLoading(true);
    try {
      const res = await cortexApi.listTasks(100);
      setTasks(res.tasks || []);
    } catch (err) {
      console.warn("Failed to load audit tasks:", err);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  const filteredTasks = tasks.filter((t) => {
    if (filter === "completed") return t.status === "completed";
    if (filter === "approval") return t.status === "waiting_approval";
    if (filter === "failed") return t.status === "failed";
    return true;
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-3xl overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Execution Audit Trail & Task History</h3>
              <p className="text-[11px] text-slate-400">Cryptographically bound action receipts and observable execution logs</p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Filter Bar */}
        <div className="flex items-center justify-between border-b border-white/5 bg-black/20 px-6 py-2 text-xs">
          <div className="flex gap-2">
            {[
              { id: "all", label: `All Tasks (${tasks.length})` },
              { id: "completed", label: "Completed" },
              { id: "approval", label: "Pending Approval" },
              { id: "failed", label: "Failed" },
            ].map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  filter === f.id
                    ? "bg-indigo-600/30 text-indigo-300 border border-indigo-500/40"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={loadAudit}
            className="flex items-center gap-1 text-[11px] text-indigo-400 hover:underline"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-3 text-xs">
          {loading ? (
            <div className="py-8 text-center text-slate-400">Loading audit history…</div>
          ) : filteredTasks.length === 0 ? (
            <div className="rounded-lg border border-white/5 bg-white/5 p-8 text-center text-slate-400">
              No audit tasks found.
            </div>
          ) : (
            filteredTasks.map((t) => {
              const audit = t.auditTrail || [];
              const hash = t.params?.approval_hash;

              return (
                <div
                  key={t.id}
                  className="rounded-xl border border-white/5 bg-black/30 p-4 space-y-2.5"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-100">{t.intent || "System Action"}</span>
                      <span className="font-mono text-[10px] text-slate-500">{t.id.slice(0, 8)}…</span>
                    </div>

                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium border ${
                        t.status === "completed"
                          ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                          : t.status === "waiting_approval"
                          ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                          : "bg-rose-500/10 text-rose-300 border-rose-500/30"
                      }`}
                    >
                      {t.status}
                    </span>
                  </div>

                  {hash && (
                    <div className="flex items-center gap-1 text-[10px] font-mono text-amber-300/80 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20 w-fit">
                      <Lock className="h-3 w-3" /> Bound Hash: {hash}
                    </div>
                  )}

                  {audit.length > 0 && (
                    <div className="space-y-1 pt-1">
                      {audit.map((ev, i) => (
                        <div key={i} className="flex items-center gap-2 text-[11px] text-slate-400 font-mono">
                          <span className="text-slate-600">↳</span>
                          <span className="text-indigo-300">{ev.event || ev.type}:</span>
                          <span>{ev.details || JSON.stringify(ev.payload || "")}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t border-white/10 bg-black/30 px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-slate-800 px-4 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
export default AuditModal;

