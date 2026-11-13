import React from "react";
import { Globe, ExternalLink, CheckCircle, Search, BookOpen, ShieldCheck } from "lucide-react";

export function WebResearchCard({ data }) {
  if (!data) return null;

  const query = data.query || data.params?.query || "Web Research";
  const results = data.results || data.sources || data.citations || [];
  const summary = data.summary || data.message || "";

  const openUrl = (url) => {
    if (!url) return;
    try {
      if (typeof window !== "undefined" && window.cortexAPI?.openExternal) {
        window.cortexAPI.openExternal(url);
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    } catch {
      window.open(url, "_blank");
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-teal-500/20 bg-teal-950/20 shadow-lg backdrop-blur-md">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-teal-500/15 bg-teal-900/30 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-teal-500/20 text-teal-400">
            <Globe className="h-4 w-4" />
          </div>
          <div>
            <div className="text-xs font-semibold text-teal-200">Evidence-Based Web Research</div>
            <div className="text-[10px] text-teal-300/70">Verified Sources & External Citations</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-[11px] font-medium text-teal-300 border border-teal-500/20">
          <ShieldCheck className="h-3 w-3 text-teal-400" /> Grounded Evidence
        </div>
      </div>

      {/* Query Bar */}
      <div className="flex items-center gap-2 border-b border-white/5 bg-black/20 px-4 py-2 text-xs text-slate-300">
        <Search className="h-3.5 w-3.5 text-teal-400 flex-shrink-0" />
        <span className="font-mono text-[11px] text-teal-200">{query}</span>
      </div>

      {/* Summary if present */}
      {summary && (
        <div className="p-4 text-xs text-slate-200 border-b border-white/5 leading-relaxed">
          {summary}
        </div>
      )}

      {/* Citations / Source Cards */}
      <div className="p-4 space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-teal-300/70 mb-1.5 flex items-center gap-1.5">
          <BookOpen className="h-3.5 w-3.5" /> Verified Sources & Citations
        </div>

        {results.length > 0 ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {results.map((res, idx) => {
              const title = res.title || res.name || `Source ${idx + 1}`;
              const url = res.url || res.link || "";
              const snippet = res.snippet || res.body || res.summary || "";
              let domain = "";
              try {
                domain = url ? new URL(url).hostname.replace("www.", "") : "";
              } catch {
                domain = "web";
              }

              return (
                <div
                  key={idx}
                  onClick={() => openUrl(url)}
                  className="group flex flex-col justify-between rounded-lg border border-white/5 bg-black/30 p-2.5 text-xs hover:border-teal-500/40 hover:bg-teal-950/30 transition-all cursor-pointer"
                >
                  <div>
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span className="rounded bg-teal-500/15 px-1.5 py-0.5 text-[10px] font-mono text-teal-300 font-medium">
                        {domain}
                      </span>
                      <ExternalLink className="h-3 w-3 text-slate-500 group-hover:text-teal-400 transition-colors" />
                    </div>
                    <div className="font-medium text-slate-200 group-hover:text-teal-200 line-clamp-1 transition-colors">
                      {title}
                    </div>
                    {snippet && (
                      <p className="mt-1 text-[11px] text-slate-400 line-clamp-2 leading-snug">
                        {snippet}
                      </p>
                    )}
                  </div>

                  <div className="mt-2 text-[10px] font-mono text-teal-400/80 truncate">
                    {url}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-xs text-slate-400 italic">No external links found.</div>
        )}
      </div>
    </div>
  );
}
export default WebResearchCard;

