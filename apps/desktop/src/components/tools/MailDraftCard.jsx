import React, { useState } from "react";
import { Mail, Check, X, Edit3, Shield, Paperclip, Send, AlertCircle, ArrowRight } from "lucide-react";

export function MailDraftCard({ task, onApprove, onCancel, onEditDraft }) {
  if (!task) return null;

  const params = task.params || {};
  const [isEditing, setIsEditing] = useState(false);
  const [recipient, setRecipient] = useState(params.recipient || "");
  const [subject, setSubject] = useState(params.subject || "");
  const [body, setBody] = useState(params.body || "");
  const [nlInstruction, setNlInstruction] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const status = task.status;
  const isPending = status === "waiting_approval";
  const isCompleted = status === "completed";
  const isCancelled = status === "cancelled" || status === "rejected";
  const isFailed = status === "failed";

  const handleSaveEdit = async () => {
    if (!onEditDraft) return;
    setIsSubmitting(true);
    try {
      await onEditDraft(task.id, { recipient, subject, body });
      setIsEditing(false);
    } catch (err) {
      alert("Failed to update draft: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleNaturalLanguageEdit = async (e) => {
    e.preventDefault();
    if (!nlInstruction.trim() || !onEditDraft) return;
    setIsSubmitting(true);
    try {
      await onEditDraft(task.id, { instruction: nlInstruction.trim() });
      setNlInstruction("");
    } catch (err) {
      alert("Failed to revise draft: " + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-sky-500/20 bg-sky-950/20 shadow-lg backdrop-blur-md transition-all">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-sky-500/15 bg-sky-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-sky-500/20 text-sky-400">
            <Mail className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold tracking-wide text-sky-200">Apple Mail Draft</div>
            <div className="text-[10px] text-sky-300/70">Deterministic Human-in-the-Loop Gateway</div>
          </div>
        </div>

        {/* Status Badge */}
        <div>
          {isPending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2.5 py-0.5 text-[11px] font-medium text-amber-300 border border-amber-500/30">
              <Shield className="h-3 w-3" /> Awaiting Explicit Approval
            </span>
          )}
          {isCompleted && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/20 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300 border border-emerald-500/30">
              <Check className="h-3 w-3" /> Sent via Apple Mail
            </span>
          )}
          {isCancelled && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/20 px-2.5 py-0.5 text-[11px] font-medium text-rose-300 border border-rose-500/30">
              <X className="h-3 w-3" /> Cancelled / Rejected
            </span>
          )}
          {isFailed && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2.5 py-0.5 text-[11px] font-medium text-red-300 border border-red-500/30">
              <AlertCircle className="h-3 w-3" /> Failed
            </span>
          )}
        </div>
      </div>

      {/* Draft Content */}
      <div className="p-4 space-y-3 text-xs">
        {isEditing ? (
          <div className="space-y-2.5">
            <div>
              <label className="block text-[10px] font-semibold text-sky-300/80 uppercase tracking-wider mb-1">To</label>
              <input
                type="text"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                className="w-full rounded-md border border-sky-500/30 bg-sky-950/40 px-2.5 py-1.5 text-xs text-sky-100 placeholder-sky-400/40 focus:border-sky-400 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-sky-300/80 uppercase tracking-wider mb-1">Subject</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full rounded-md border border-sky-500/30 bg-sky-950/40 px-2.5 py-1.5 text-xs text-sky-100 placeholder-sky-400/40 focus:border-sky-400 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[10px] font-semibold text-sky-300/80 uppercase tracking-wider mb-1">Message Body</label>
              <textarea
                rows={5}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full rounded-md border border-sky-500/30 bg-sky-950/40 p-2.5 text-xs text-sky-100 placeholder-sky-400/40 focus:border-sky-400 focus:outline-none"
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="rounded-md border border-slate-600 bg-slate-800/60 px-3 py-1 text-xs text-slate-300 hover:bg-slate-700/60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                disabled={isSubmitting}
                className="rounded-md bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500"
              >
                Save Changes
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-[50px_1fr] items-center gap-2 border-b border-sky-500/10 pb-2">
              <span className="text-slate-400 font-medium">To:</span>
              <span className="font-mono text-sky-200 bg-sky-500/10 px-2 py-0.5 rounded w-fit">{params.recipient || "Unspecified recipient"}</span>
            </div>
            <div className="grid grid-cols-[50px_1fr] items-center gap-2 border-b border-sky-500/10 pb-2">
              <span className="text-slate-400 font-medium">Subject:</span>
              <span className="font-semibold text-slate-100">{params.subject || "No Subject"}</span>
            </div>
            <div className="pt-1">
              <div className="whitespace-pre-wrap rounded-lg bg-black/25 p-3 text-slate-200 border border-white/5 font-sans leading-relaxed">
                {params.body || "Empty body"}
              </div>
            </div>

            {params.attachments && params.attachments.length > 0 && (
              <div className="flex items-center gap-2 pt-1 text-[11px] text-slate-400">
                <Paperclip className="h-3.5 w-3.5 text-sky-400" />
                <span>Attachments: {params.attachments.join(", ")}</span>
              </div>
            )}
          </>
        )}

        {/* Natural Language Modification Input */}
        {isPending && !isEditing && (
          <form onSubmit={handleNaturalLanguageEdit} className="pt-2">
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Instruct revision: e.g. 'Make it more formal' or 'Add Rahul in CC'…"
                value={nlInstruction}
                onChange={(e) => setNlInstruction(e.target.value)}
                className="flex-1 rounded-lg border border-sky-500/20 bg-sky-950/40 px-3 py-1.5 text-xs text-sky-100 placeholder-sky-400/40 focus:border-sky-400 focus:outline-none"
              />
              <button
                type="submit"
                disabled={isSubmitting || !nlInstruction.trim()}
                className="inline-flex items-center gap-1 rounded-lg bg-sky-600/40 px-3 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-600 hover:text-white disabled:opacity-40"
              >
                Revise <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </form>
        )}

        {/* Security / Cryptographic Hash Token Warning */}
        {params.approval_hash && (
          <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 p-2 text-[10px] text-amber-300 border border-amber-500/20">
            <Shield className="h-3.5 w-3.5 flex-shrink-0 text-amber-400" />
            <div className="truncate">
              Cryptographically bound token: <code className="font-mono text-amber-200">{params.approval_hash.slice(0, 16)}…</code>. Replay and parameter tampering strictly prevented.
            </div>
          </div>
        )}

        {/* Action Controls for Pending Approvals */}
        {isPending && (
          <div className="flex items-center justify-between pt-3 border-t border-sky-500/15">
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/80 transition-colors"
            >
              <Edit3 className="h-3.5 w-3.5" /> Manual Edit
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onCancel && onCancel(task.id)}
                disabled={isSubmitting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-950/40 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:bg-rose-900/60 hover:text-white transition-colors"
              >
                <X className="h-3.5 w-3.5" /> Deny / Cancel
              </button>

              <button
                type="button"
                onClick={() => onApprove && onApprove(task.id, params.approval_hash)}
                disabled={isSubmitting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-bold text-white shadow-md hover:bg-emerald-500 hover:shadow-emerald-500/25 transition-all"
              >
                <Check className="h-4 w-4" /> Approve & Send
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
export default MailDraftCard;

