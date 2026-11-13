import React from "react";
import { Eye, ShieldCheck, Monitor, CheckCircle, AlertTriangle } from "lucide-react";

export function ScreenVisionCard({ data }) {
  if (!data) return null;

  const activeApp = data.active_app || data.app || "Frontmost Application";
  const windowTitle = data.window_title || data.title || "Active Window";
  const elements = data.elements || data.visible_elements || [];
  const ocrText = data.ocr_text || data.text || "";
  const injectionDetected = data.prompt_injection_detected || false;

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-purple-500/20 bg-purple-950/20 shadow-lg backdrop-blur-md">
      <div className="flex items-center justify-between border-b border-purple-500/15 bg-purple-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-purple-500/20 text-purple-400">
            <Eye className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-purple-200">Screen Vision & Intelligence</div>
            <div className="text-[10px] text-purple-300/70">macOS Accessibility Hierarchy & OCR</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 rounded-full bg-purple-500/10 px-2 py-0.5 text-[10px] font-medium text-purple-300 border border-purple-500/20">
          {injectionDetected ? (
            <span className="flex items-center gap-1 text-rose-300">
              <AlertTriangle className="h-3 w-3 text-rose-400" /> Adversarial Trigger Detected
            </span>
          ) : (
            <span className="flex items-center gap-1 text-emerald-300">
              <ShieldCheck className="h-3 w-3 text-emerald-400" /> Untrusted Content Sanitized
            </span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-2.5 text-xs">
        <div className="grid grid-cols-[80px_1fr] items-center gap-2 border-b border-white/5 pb-2">
          <span className="text-slate-400 font-medium">Active App:</span>
          <span className="font-semibold text-purple-200">{activeApp}</span>
        </div>

        <div className="grid grid-cols-[80px_1fr] items-center gap-2 border-b border-white/5 pb-2">
          <span className="text-slate-400 font-medium">Window Title:</span>
          <span className="font-mono text-slate-200 truncate">{windowTitle}</span>
        </div>

        {elements.length > 0 && (
          <div className="pt-1">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-purple-300/70 mb-1.5">
              Detected Interactive Elements ({elements.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {elements.slice(0, 8).map((el, idx) => (
                <span
                  key={idx}
                  className="rounded-md border border-purple-500/20 bg-purple-950/40 px-2 py-0.5 text-[11px] text-purple-200 font-mono"
                >
                  {typeof el === "string" ? el : el.title || el.role || `Element ${idx + 1}`}
                </span>
              ))}
            </div>
          </div>
        )}

        {ocrText && (
          <div className="pt-1">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">OCR Text Extraction</div>
            <div className="max-h-24 overflow-y-auto rounded-lg bg-black/30 p-2 font-mono text-[11px] text-slate-300 border border-white/5 whitespace-pre-wrap">
              {ocrText}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
export default ScreenVisionCard;

