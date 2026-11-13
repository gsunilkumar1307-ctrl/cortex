import React, { useState } from "react";
import { ShieldAlert, Check, X, AlertTriangle, Lock } from "lucide-react";

export function ApprovalCard({ actionDetails, onApprove, onDeny }) {
  if (!actionDetails) return null;

  const [submitting, setSubmitting] = useState(false);
  const {
    id,
    action = "Consequential Operation",
    target = "Local System",
    parameters = {},
    consequences = "This action will directly modify system or external state.",
    approval_hash = "",
    status = "waiting_approval",
  } = actionDetails;

  const isPending = status === "waiting_approval";
  const isApproved = status === "completed" || status === "approved";
  const isDenied = status === "cancelled" || status === "denied" || status === "rejected";

  const handleApprove = async () => {
    if (!onApprove) return;
    setSubmitting(true);
    try {
      await onApprove(id, approval_hash);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeny = async () => {
    if (!onDeny) return;
    setSubmitting(true);
    try {
      await onDeny(id);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-amber-500/30 bg-amber-950/25 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-amber-500/20 bg-amber-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/20 text-amber-300">
            <ShieldAlert className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-amber-200">Security Gate: Explicit Approval Required</div>
            <div className="text-[10px] text-amber-300/70">Cryptographically bound human authorization</div>
          </div>
        </div>

        <div>
          {isApproved && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-300 border border-emerald-500/30">
              <Check className="h-3 w-3" /> Approved & Executed
            </span>
          )}
          {isDenied && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-medium text-rose-300 border border-rose-500/30">
              <X className="h-3 w-3" /> Denied by User
            </span>
          )}
          {isPending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-300 border border-amber-500/30">
              <Lock className="h-3 w-3" /> Confirmation Pending
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3 text-xs">
        <div className="grid grid-cols-[80px_1fr] items-center gap-2 border-b border-white/5 pb-2">
          <span className="text-slate-400 font-medium">Action:</span>
          <span className="font-semibold text-amber-100">{action}</span>
        </div>

        <div className="grid grid-cols-[80px_1fr] items-center gap-2 border-b border-white/5 pb-2">
          <span className="text-slate-400 font-medium">Target:</span>
          <span className="font-mono text-slate-200">{target}</span>
        </div>

        {Object.keys(parameters).length > 0 && (
          <div className="border-b border-white/5 pb-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Parameters</div>
            <div className="rounded-lg bg-black/30 p-2 font-mono text-[11px] text-slate-300 border border-white/5 whitespace-pre-wrap">
              {JSON.stringify(parameters, null, 2)}
            </div>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-lg bg-amber-500/10 p-2.5 text-amber-200 border border-amber-500/20">
          <AlertTriangle className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-[11px] leading-relaxed">
            <strong className="text-amber-100">Consequences:</strong> {consequences}
          </div>
        </div>

        {approval_hash && (
          <div className="text-[10px] font-mono text-slate-400 truncate">
            Verification Token: <span className="text-amber-300">{approval_hash}</span>
          </div>
        )}

        {isPending && (
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-amber-500/15">
            <button
              type="button"
              onClick={handleDeny}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-950/40 px-3.5 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-900/60 hover:text-white transition-colors"
            >
              <X className="h-3.5 w-3.5" /> Deny Action
            </button>

            <button
              type="button"
              onClick={handleApprove}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-4 py-1.5 text-xs font-bold text-black shadow-md hover:bg-amber-400 hover:shadow-amber-500/25 transition-all"
            >
              <Check className="h-4 w-4" /> Explicitly Approve
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
export default ApprovalCard;

