import React from "react";
import { Terminal, AppWindow, Folder, MessageSquare, Check, X, ExternalLink, Activity } from "lucide-react";

export function DesktopActionCard({ task }) {
  if (!task) return null;

  const params = task.params || {};
  const appName = params.app || params.application || params.target_app || task.intent || "macOS System";
  const action = params.action || task.command || "Execute Command";
  const result = task.result || params.result || params.observation || null;
  const status = task.status;

  const isSuccess = status === "completed";
  const isFailed = status === "failed";
  const isPending = status === "running" || status === "executing";

  const getAppIcon = (name) => {
    const l = String(name).toLowerCase();
    if (l.includes("finder") || l.includes("file")) return <Folder className="h-4 w-4" />;
    if (l.includes("terminal") || l.includes("bash") || l.includes("shell")) return <Terminal className="h-4 w-4" />;
    if (l.includes("whatsapp") || l.includes("chat")) return <MessageSquare className="h-4 w-4" />;
    return <AppWindow className="h-4 w-4" />;
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/40 shadow-lg backdrop-blur-md">
      <div className="flex items-center justify-between border-b border-white/5 bg-slate-800/40 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-700/50 text-slate-200">
            {getAppIcon(appName)}
          </div>
          <div>
            <div className="text-xs font-semibold text-slate-200">{appName}</div>
            <div className="text-[10px] text-slate-400">Desktop Operator Action</div>
          </div>
        </div>

        <div>
          {isSuccess && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300 border border-emerald-500/30">
              <Check className="h-3 w-3" /> Completed
            </span>
          )}
          {isPending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] font-medium text-sky-300 border border-sky-500/30">
              <Activity className="h-3 w-3 animate-spin" /> Executing
            </span>
          )}
          {isFailed && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-medium text-rose-300 border border-rose-500/30">
              <X className="h-3 w-3" /> Failed
            </span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-2 text-xs">
        <div className="grid grid-cols-[60px_1fr] items-center gap-2">
          <span className="text-slate-400 font-medium">Action:</span>
          <span className="font-mono text-slate-200 bg-white/5 px-2 py-0.5 rounded w-fit">{action}</span>
        </div>

        {params.path && (
          <div className="grid grid-cols-[60px_1fr] items-center gap-2">
            <span className="text-slate-400 font-medium">Path:</span>
            <span className="font-mono text-slate-300 truncate">{params.path}</span>
          </div>
        )}

        {result && (
          <div className="mt-2 pt-2 border-t border-white/5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Observable Result</div>
            <div className="whitespace-pre-wrap rounded-lg bg-black/30 p-2.5 font-mono text-[11px] text-slate-300 border border-white/5">
              {typeof result === "object" ? JSON.stringify(result, null, 2) : String(result)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
export default DesktopActionCard;

