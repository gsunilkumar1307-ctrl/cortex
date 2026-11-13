import React from "react";
import { AlertOctagon, RefreshCw, HelpCircle } from "lucide-react";

export function ToolErrorCard({ error, onRetry }) {
  if (!error) return null;

  const errorMessage = typeof error === "string" ? error : error.message || error.detail || "An unexpected error occurred during execution.";
  const recovery = error.recovery || "Check system permissions, network connectivity, or verify that the target application is installed and active.";

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-rose-500/30 bg-rose-950/25 shadow-lg backdrop-blur-md">
      <div className="flex items-center justify-between border-b border-rose-500/20 bg-rose-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-500/20 text-rose-300">
            <AlertOctagon className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-rose-200">Execution Blocked / Error Encountered</div>
            <div className="text-[10px] text-rose-300/70">Observable Diagnostic & Safe Recovery</div>
          </div>
        </div>
      </div>

      <div className="p-4 space-y-3 text-xs">
        <div className="rounded-lg bg-black/30 p-2.5 font-mono text-[11px] text-rose-200 border border-rose-500/20 whitespace-pre-wrap">
          {errorMessage}
        </div>

        <div className="flex items-start gap-2 text-slate-300">
          <HelpCircle className="h-4 w-4 text-sky-400 flex-shrink-0 mt-0.5" />
          <div className="text-[11px] leading-relaxed">
            <strong className="text-slate-200">Suggested Recovery:</strong> {recovery}
          </div>
        </div>

        {onRetry && (
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-900/40 px-3 py-1.5 text-xs font-medium text-rose-200 hover:bg-rose-800/60 hover:text-white transition-colors"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Retry Operation
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
export default ToolErrorCard;

