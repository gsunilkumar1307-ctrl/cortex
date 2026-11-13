import React from "react";
import { CheckCircle2, Clock, Play, Pause, XCircle, AlertTriangle, Shield, ArrowRight, ListOrdered } from "lucide-react";

export function TaskPlanCard({ task, onPause, onCancel, onResume }) {
  if (!task) return null;

  // Extract structured plan data from task or task params
  const plan = task.plan || task.params?.plan || [];
  const steps = Array.isArray(plan) ? plan : (task.auditTrail || []);
  const intent = task.intent || task.params?.intent || "Task Plan";
  const status = task.status;

  // Calculate actual progress based on real step states
  const totalSteps = steps.length || 1;
  const completedSteps = steps.filter(s => s.status === "completed" || s.state === "completed" || s.event === "step_completed").length;
  const progressPercent = Math.min(100, Math.round((completedSteps / totalSteps) * 100));

  const getStepIcon = (stepStatus) => {
    switch (stepStatus) {
      case "completed":
        return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
      case "running":
      case "executing":
        return <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />;
      case "waiting_approval":
        return <Shield className="h-4 w-4 text-amber-400" />;
      case "blocked":
      case "failed":
        return <XCircle className="h-4 w-4 text-rose-400" />;
      default:
        return <Clock className="h-4 w-4 text-slate-500" />;
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-indigo-500/20 bg-indigo-950/20 shadow-lg backdrop-blur-md">
      {/* Plan Header */}
      <div className="flex items-center justify-between border-b border-indigo-500/15 bg-indigo-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/20 text-indigo-400">
            <ListOrdered className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-indigo-200">{intent}</div>
            <div className="text-[10px] text-indigo-300/70">Structured Autonomous Plan Execution</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status === "paused" ? (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-300 border border-amber-500/30">
              Paused
            </span>
          ) : status === "completed" ? (
            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300 border border-emerald-500/30">
              Completed
            </span>
          ) : (
            <span className="rounded-full bg-indigo-500/20 px-2 py-0.5 text-[10px] font-medium text-indigo-300 border border-indigo-500/30">
              In Progress ({progressPercent}%)
            </span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-1.5 w-full bg-black/40">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-sky-400 transition-all duration-300"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      {/* Steps List */}
      <div className="p-4 space-y-2">
        {steps.length > 0 ? (
          steps.map((step, idx) => {
            const stepTitle = step.title || step.description || step.name || step.action || `Step ${idx + 1}`;
            const stepStatus = step.status || step.state || (idx < completedSteps ? "completed" : idx === completedSteps ? "running" : "pending");
            const stepDeps = step.depends_on || step.dependencies;

            return (
              <div
                key={idx}
                className="flex items-start gap-3 rounded-lg border border-white/5 bg-black/20 p-2.5 text-xs transition-colors"
              >
                <div className="mt-0.5 flex-shrink-0">{getStepIcon(stepStatus)}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-200">{stepTitle}</span>
                    <span className="text-[10px] font-mono capitalize text-slate-400">{stepStatus.replace("_", " ")}</span>
                  </div>

                  {step.details && (
                    <div className="mt-0.5 text-[11px] text-slate-400">{step.details}</div>
                  )}

                  {stepDeps && stepDeps.length > 0 && (
                    <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-500 font-mono">
                      <span>Depends on:</span>
                      <span className="bg-white/5 px-1.5 py-0.2 rounded text-slate-400">{Array.isArray(stepDeps) ? stepDeps.join(", ") : stepDeps}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        ) : (
          <div className="text-center py-3 text-xs text-slate-400">
            {task.description || "Executing plan sequence…"}
          </div>
        )}

        {/* Action Controls */}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-indigo-500/10">
          {status !== "completed" && status !== "cancelled" && (
            <>
              {status === "paused" ? (
                <button
                  type="button"
                  onClick={() => onResume && onResume(task.id)}
                  className="inline-flex items-center gap-1 rounded-md border border-indigo-500/30 bg-indigo-900/40 px-2.5 py-1 text-[11px] font-medium text-indigo-200 hover:bg-indigo-800/60"
                >
                  <Play className="h-3 w-3" /> Resume Plan
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => onPause && onPause(task.id)}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800/50 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:bg-slate-700/60"
                >
                  <Pause className="h-3 w-3" /> Pause
                </button>
              )}

              <button
                type="button"
                onClick={() => onCancel && onCancel(task.id)}
                className="inline-flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-950/30 px-2.5 py-1 text-[11px] font-medium text-rose-300 hover:bg-rose-900/40"
              >
                <XCircle className="h-3 w-3" /> Cancel Plan
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
export default TaskPlanCard;

