import React, { useState, useEffect } from "react";
import { X, Shield, Sliders, Mic, Volume2, Database, Trash2, CheckCircle2, Sparkles, RefreshCw } from "lucide-react";
import cortexApi from "../../runtime/cortexApi";

export function SettingsModal({
  isOpen,
  onClose,
  speakingRate = 1.0,
  setSpeakingRate,
  chimesEnabled = true,
  setChimesEnabled,
  wakeWordEnabled = true,
  setWakeWordEnabled,
  onClearHistory,
}) {
  const [activeTab, setActiveTab] = useState("memory");
  const [memories, setMemories] = useState([]);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadMemories();
    }
  }, [isOpen]);

  const loadMemories = async () => {
    setLoadingMemories(true);
    try {
      const res = await cortexApi.listMemories();
      setMemories(res.items || []);
    } catch (err) {
      console.warn("Failed to load memories:", err);
    } finally {
      setLoadingMemories(false);
    }
  };

  const handleDeleteMemory = async (id) => {
    try {
      await cortexApi.deleteMemory(id);
      loadMemories();
    } catch (err) {
      alert("Error deleting memory: " + err.message);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl flex flex-col max-h-[85vh]">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <Sliders className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Cortex Preferences & Configuration</h3>
              <p className="text-[11px] text-slate-400">Manage persistent memory categories, voice, and system parameters</p>
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

        {/* Tabs */}
        <div className="flex border-b border-white/5 bg-black/20 px-6">
          <button
            type="button"
            onClick={() => setActiveTab("memory")}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition-colors ${
              activeTab === "memory"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Database className="h-3.5 w-3.5" /> Memory Categories ({memories.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("voice")}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition-colors ${
              activeTab === "voice"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Volume2 className="h-3.5 w-3.5" /> Voice & Speech
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("model")}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition-colors ${
              activeTab === "model"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sparkles className="h-3.5 w-3.5" /> Model & Intelligence
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 text-xs">
          {activeTab === "memory" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-indigo-500/20 bg-indigo-950/20 p-4">
                <div className="flex items-center gap-2 text-indigo-300 font-semibold mb-1">
                  <Shield className="h-4 w-4" /> Encrypted Local Relational Memory
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Cortex stores facts and preferences in a local AES-256 encrypted SQLite database (<code>cortex-memory.sqlite3</code>). Memory categories remain independently configurable and are never uploaded to third-party clouds.
                </p>
              </div>

              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">Stored Memory Items</span>
                <button
                  type="button"
                  onClick={loadMemories}
                  className="flex items-center gap-1 text-[11px] text-indigo-400 hover:underline"
                >
                  <RefreshCw className="h-3 w-3" /> Refresh
                </button>
              </div>

              {loadingMemories ? (
                <div className="py-6 text-center text-slate-400">Loading stored memories…</div>
              ) : memories.length === 0 ? (
                <div className="rounded-lg border border-white/5 bg-white/5 p-6 text-center text-slate-400">
                  No memories currently stored.
                </div>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {memories.map((m) => (
                    <div
                      key={m.id}
                      className="flex items-start justify-between rounded-lg border border-white/5 bg-black/30 p-3 text-xs"
                    >
                      <div className="space-y-1 min-w-0 flex-1 pr-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-indigo-300 font-medium">{m.id}</span>
                          <span className="rounded bg-white/10 px-1.5 py-0.2 text-[9px] uppercase font-mono text-slate-400">
                            {m.kind}
                          </span>
                        </div>
                        <div className="font-mono text-[11px] text-slate-300 truncate">
                          {JSON.stringify(m.payload)}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleDeleteMemory(m.id)}
                        className="rounded p-1 text-slate-500 hover:bg-rose-500/20 hover:text-rose-400 transition-colors"
                        title="Delete memory"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Clear conversation session history */}
              <div className="pt-4 border-t border-white/5 flex items-center justify-between">
                <div>
                  <div className="font-medium text-slate-200">Clear Active Session Context</div>
                  <div className="text-[10px] text-slate-400">Resets in-memory conversation state</div>
                </div>

                {confirmClear ? (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmClear(false)}
                      className="rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (onClearHistory) onClearHistory();
                        setConfirmClear(false);
                      }}
                      className="rounded-lg bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500"
                    >
                      Confirm Clear
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmClear(true)}
                    className="rounded-lg border border-rose-500/30 bg-rose-950/20 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-900/40"
                  >
                    Clear History
                  </button>
                )}
              </div>
            </div>
          )}

          {activeTab === "voice" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between py-2 border-b border-white/5">
                <div>
                  <div className="font-medium text-slate-200">Wake Word Spotting</div>
                  <div className="text-[10px] text-slate-400">Listens for 'Hey Cortex', 'ಹೇ ಕಾರ್ಟೆಕ್ಸ್', 'सुनो कोर्टेक्स'</div>
                </div>
                <input
                  type="checkbox"
                  checked={wakeWordEnabled}
                  onChange={(e) => setWakeWordEnabled && setWakeWordEnabled(e.target.checked)}
                  className="h-4 w-4 rounded accent-indigo-600"
                />
              </div>

              <div className="flex items-center justify-between py-2 border-b border-white/5">
                <div>
                  <div className="font-medium text-slate-200">Audio Feedback Chimes</div>
                  <div className="text-[10px] text-slate-400">Play pleasant macOS sound chimes on wake, success, and alert</div>
                </div>
                <input
                  type="checkbox"
                  checked={chimesEnabled}
                  onChange={(e) => setChimesEnabled && setChimesEnabled(e.target.checked)}
                  className="h-4 w-4 rounded accent-indigo-600"
                />
              </div>

              <div className="space-y-2 py-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-200">Speaking Rate</span>
                  <span className="font-mono text-indigo-300">{speakingRate}x</span>
                </div>
                <input
                  type="range"
                  min="0.75"
                  max="1.5"
                  step="0.05"
                  value={speakingRate}
                  onChange={(e) => setSpeakingRate && setSpeakingRate(parseFloat(e.target.value))}
                  className="w-full accent-indigo-600"
                />
              </div>
            </div>
          )}

          {activeTab === "model" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-white/5 bg-black/30 p-4 space-y-3">
                <div className="flex items-center gap-2 text-indigo-300 font-semibold">
                  <Sparkles className="h-4 w-4" /> Primary AI Model: Google Gemini
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Cortex uses Google Gemini with multimodal vision for intent classification, autonomous planning, and screen element resolution.
                </p>
                <div className="flex items-center gap-2 text-[11px] text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" /> Configured via <code>.env</code> (GEMINI_API_KEY)
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-black/30 p-4 space-y-2">
                <div className="font-semibold text-slate-200">Deterministic Fallback Engine</div>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  If the AI model is temporarily rate-limited or unavailable, Cortex seamlessly falls back to local deterministic rule classifiers and AppleScript automations, guaranteeing uninterrupted desktop operation.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-white/10 bg-black/30 px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 shadow-md transition-all"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
export default SettingsModal;

