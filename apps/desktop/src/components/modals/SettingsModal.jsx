import React, { useState, useEffect, useRef } from "react";
import {
  X, Shield, Sliders, Mic, Volume2, Database, Trash2,
  CheckCircle2, Sparkles, RefreshCw, Command, AppWindow,
  Radio, Play, AlertCircle, Headphones
} from "lucide-react";
import cortexApi from "../../runtime/cortexApi";
import AudioVisualizer from "../AudioVisualizer";

const cortexBridge = typeof window !== "undefined" && window.cortexAPI ? window.cortexAPI : null;

export function SettingsModal({
  isOpen,
  onClose,
  speakingRate = 1.0,
  setSpeakingRate,
  chimesEnabled = true,
  setChimesEnabled,
  wakeWordEnabled = false,
  setWakeWordEnabled,
  onClearHistory,
  onPlayChime = null,
}) {
  const [activeTab, setActiveTab] = useState("companion");
  const [memories, setMemories] = useState([]);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  // Desktop companion settings state
  const [companionConfig, setCompanionConfig] = useState({
    globalShortcut: "Command+Shift+A",
    alwaysOnTop: true,
    closeOnBlur: false,
    escapeHides: true,
    rememberBounds: true,
    startMinimized: false,
    launchAtLogin: false,
    wakeWordEnabled: false,
    wakeWordSensitivity: 0.5,
    audioInputDevice: "default",
    audioOutputDevice: "default",
  });
  const [recordingShortcut, setRecordingShortcut] = useState(false);
  const [shortcutError, setShortcutError] = useState("");

  // Audio devices state
  const [audioInputs, setAudioInputs] = useState([]);
  const [audioOutputs, setAudioOutputs] = useState([]);
  const [micTestStream, setMicTestStream] = useState(null);
  const [isTestingMic, setIsTestingMic] = useState(false);

  // Load memories and companion settings on open
  useEffect(() => {
    if (isOpen) {
      loadMemories();
      loadCompanionSettings();
      enumerateAudioDevices();
    } else {
      stopMicTest();
    }
  }, [isOpen]);

  const loadCompanionSettings = async () => {
    if (!cortexBridge?.getCompanionSettings) return;
    try {
      const cfg = await cortexBridge.getCompanionSettings();
      if (cfg) setCompanionConfig(cfg);
    } catch (err) {
      console.warn("Failed to load companion settings:", err);
    }
  };

  const updateSetting = async (key, value) => {
    const updated = { ...companionConfig, [key]: value };
    setCompanionConfig(updated);
    if (cortexBridge?.updateCompanionSettings) {
      try {
        await cortexBridge.updateCompanionSettings({ [key]: value });
      } catch (err) {
        console.warn("Failed to update companion setting:", err);
      }
    }
  };

  const enumerateAudioDevices = async () => {
    if (!navigator?.mediaDevices?.enumerateDevices) return;
    try {
      // Request temporary mic permission to ensure device labels are populated
      await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => {});
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((d) => d.kind === "audioinput");
      const outputs = devices.filter((d) => d.kind === "audiooutput");
      setAudioInputs(inputs);
      setAudioOutputs(outputs);
    } catch (err) {
      console.warn("Error enumerating audio devices:", err);
    }
  };

  const toggleMicTest = async () => {
    if (isTestingMic) {
      stopMicTest();
    } else {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: companionConfig.audioInputDevice && companionConfig.audioInputDevice !== "default"
            ? { deviceId: { exact: companionConfig.audioInputDevice } }
            : true,
        });
        setMicTestStream(stream);
        setIsTestingMic(true);
      } catch (err) {
        alert("Microphone test error: " + err.message);
      }
    }
  };

  const stopMicTest = () => {
    if (micTestStream) {
      micTestStream.getTracks().forEach((t) => t.stop());
      setMicTestStream(null);
    }
    setIsTestingMic(false);
  };

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

  // Keyboard shortcut recorder
  const handleShortcutKeyDown = async (e) => {
    if (!recordingShortcut) return;
    e.preventDefault();
    e.stopPropagation();

    if (e.key === "Escape") {
      setRecordingShortcut(false);
      setShortcutError("");
      return;
    }

    const parts = [];
    if (e.metaKey) parts.push("Command");
    if (e.ctrlKey) parts.push("Control");
    if (e.altKey) parts.push("Alt");
    if (e.shiftKey) parts.push("Shift");

    const key = e.key.toUpperCase();
    if (!["META", "CONTROL", "ALT", "SHIFT"].includes(key)) {
      parts.push(key === " " ? "Space" : key);
      const newAcc = parts.join("+");

      if (cortexBridge?.setGlobalShortcut) {
        const res = await cortexBridge.setGlobalShortcut(newAcc);
        if (res.success) {
          setCompanionConfig((prev) => ({ ...prev, globalShortcut: res.shortcut }));
          setRecordingShortcut(false);
          setShortcutError("");
        } else {
          setShortcutError(res.error || "Shortcut cannot be registered.");
        }
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div
      onKeyDown={recordingShortcut ? handleShortcutKeyDown : undefined}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4 animate-in fade-in duration-200"
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-slate-900 shadow-2xl flex flex-col max-h-[85vh]">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <Sliders className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Cortex Desktop Companion Settings</h3>
              <p className="text-[11px] text-slate-400">Native macOS shortcuts, floating assistant, voice devices & memory</p>
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
        <div className="flex border-b border-white/5 bg-black/20 px-6 overflow-x-auto">
          <button
            type="button"
            onClick={() => { setActiveTab("companion"); stopMicTest(); }}
            className={`flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold whitespace-nowrap transition-colors ${
              activeTab === "companion"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <AppWindow className="h-3.5 w-3.5" /> Desktop Companion
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("voice")}
            className={`flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold whitespace-nowrap transition-colors ${
              activeTab === "voice"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Headphones className="h-3.5 w-3.5" /> Voice & Audio Devices
          </button>
          <button
            type="button"
            onClick={() => { setActiveTab("wakeword"); stopMicTest(); }}
            className={`flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold whitespace-nowrap transition-colors ${
              activeTab === "wakeword"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Radio className="h-3.5 w-3.5" /> Wake Word
          </button>
          <button
            type="button"
            onClick={() => { setActiveTab("memory"); stopMicTest(); }}
            className={`flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold whitespace-nowrap transition-colors ${
              activeTab === "memory"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Database className="h-3.5 w-3.5" /> Memory ({memories.length})
          </button>
          <button
            type="button"
            onClick={() => { setActiveTab("model"); stopMicTest(); }}
            className={`flex items-center gap-2 border-b-2 px-3 py-3 text-xs font-semibold whitespace-nowrap transition-colors ${
              activeTab === "model"
                ? "border-indigo-500 text-indigo-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sparkles className="h-3.5 w-3.5" /> Model
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 text-xs">
          {/* TAB 1: DESKTOP COMPANION */}
          {activeTab === "companion" && (
            <div className="space-y-5">
              {/* Global Keyboard Shortcut */}
              <div className="rounded-xl border border-indigo-500/20 bg-indigo-950/20 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-white flex items-center gap-1.5">
                      <Command className="h-4 w-4 text-indigo-400" /> Global Summon Shortcut
                    </div>
                    <div className="text-[11px] text-slate-400">
                      Press anywhere in macOS to summon or dismiss the floating assistant
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="rounded-lg bg-black/40 border border-indigo-500/40 px-3 py-1 font-mono text-xs font-bold text-indigo-300">
                      {recordingShortcut ? "Press keys… (Esc to cancel)" : companionConfig.globalShortcut}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setRecordingShortcut((r) => !r);
                        setShortcutError("");
                      }}
                      className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-500 transition-colors"
                    >
                      {recordingShortcut ? "Cancel" : "Change"}
                    </button>
                  </div>
                </div>

                {shortcutError && (
                  <div className="text-[11px] text-rose-400 flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" /> {shortcutError}
                  </div>
                )}
              </div>

              {/* Window Behaviors */}
              <div className="space-y-3">
                <div className="font-semibold text-slate-200">Floating Assistant Window Behavior</div>

                <div className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="font-medium text-slate-200">Always on Top</div>
                    <div className="text-[10px] text-slate-400">Keep floating assistant floating above all macOS application windows</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(companionConfig.alwaysOnTop)}
                    onChange={(e) => updateSetting("alwaysOnTop", e.target.checked)}
                    className="h-4 w-4 rounded accent-indigo-600"
                  />
                </div>

                <div className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="font-medium text-slate-200">Close on Blur</div>
                    <div className="text-[10px] text-slate-400">Dismiss the floating assistant when clicking away or focusing another application</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(companionConfig.closeOnBlur)}
                    onChange={(e) => updateSetting("closeOnBlur", e.target.checked)}
                    className="h-4 w-4 rounded accent-indigo-600"
                  />
                </div>

                <div className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="font-medium text-slate-200">Escape Key Hides Window</div>
                    <div className="text-[10px] text-slate-400">Pressing Esc when idle dismisses Cortex to the macOS menu bar</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(companionConfig.escapeHides)}
                    onChange={(e) => updateSetting("escapeHides", e.target.checked)}
                    className="h-4 w-4 rounded accent-indigo-600"
                  />
                </div>

                <div className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="font-medium text-slate-200">Remember Position & Size</div>
                    <div className="text-[10px] text-slate-400">Preserve your custom window placement across restarts</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(companionConfig.rememberBounds)}
                    onChange={(e) => updateSetting("rememberBounds", e.target.checked)}
                    className="h-4 w-4 rounded accent-indigo-600"
                  />
                </div>

                <div className="flex items-center justify-between py-2 border-b border-white/5">
                  <div>
                    <div className="font-medium text-slate-200">Launch at macOS Login</div>
                    <div className="text-[10px] text-slate-400">Automatically start Cortex in the menu bar when you log into Mac</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(companionConfig.launchAtLogin)}
                    onChange={(e) => updateSetting("launchAtLogin", e.target.checked)}
                    className="h-4 w-4 rounded accent-indigo-600"
                  />
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: VOICE & AUDIO DEVICES */}
          {activeTab === "voice" && (
            <div className="space-y-4">
              {/* Microphone Device */}
              <div className="space-y-1.5">
                <label className="font-medium text-slate-200 flex items-center gap-1.5">
                  <Mic className="h-4 w-4 text-indigo-400" /> Microphone Input Device
                </label>
                <select
                  value={companionConfig.audioInputDevice || "default"}
                  onChange={(e) => updateSetting("audioInputDevice", e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none"
                >
                  <option value="default">Default System Microphone</option>
                  {audioInputs.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Microphone (${d.deviceId.slice(0, 8)}…)`}
                    </option>
                  ))}
                </select>
              </div>

              {/* Mic Test */}
              <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/30 p-3">
                <div className="space-y-1">
                  <div className="font-medium text-slate-200">Microphone Input Level Test</div>
                  <div className="text-[10px] text-slate-400">Speak to test your microphone levels</div>
                </div>

                <div className="flex items-center gap-3">
                  {isTestingMic && (
                    <div className="w-24">
                      <AudioVisualizer stream={micTestStream} isActive={true} mode="listening" barCount={12} height={18} />
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={toggleMicTest}
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                      isTestingMic ? "bg-amber-500 text-black" : "bg-white/10 text-white hover:bg-white/20"
                    }`}
                  >
                    {isTestingMic ? "Stop Test" : "Test Mic"}
                  </button>
                </div>
              </div>

              {/* Speaker Device */}
              <div className="space-y-1.5 pt-2">
                <label className="font-medium text-slate-200 flex items-center gap-1.5">
                  <Volume2 className="h-4 w-4 text-emerald-400" /> Speaker Output Device
                </label>
                <select
                  value={companionConfig.audioOutputDevice || "default"}
                  onChange={(e) => updateSetting("audioOutputDevice", e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none"
                >
                  <option value="default">Default System Speakers</option>
                  {audioOutputs.map((d) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Speaker (${d.deviceId.slice(0, 8)}…)`}
                    </option>
                  ))}
                </select>
              </div>

              {/* Speaker Test */}
              <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/30 p-3">
                <div>
                  <div className="font-medium text-slate-200">Speaker Audio Test</div>
                  <div className="text-[10px] text-slate-400">Play a test sound to verify speaker output</div>
                </div>

                <button
                  type="button"
                  onClick={() => onPlayChime && onPlayChime("wake")}
                  className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/20 transition-colors"
                >
                  <Play className="h-3.5 w-3.5" /> Play Chime
                </button>
              </div>

              {/* Speaking Rate */}
              <div className="space-y-2 py-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-200">TTS Speaking Rate</span>
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

              {/* Chimes toggle */}
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
            </div>
          )}

          {/* TAB 3: WAKE WORD */}
          {activeTab === "wakeword" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-amber-500/20 bg-amber-950/20 p-4 space-y-2">
                <div className="flex items-center gap-2 text-amber-300 font-semibold">
                  <Radio className="h-4 w-4" /> On-Device Wake-Word Detection
                </div>
                <p className="text-[11px] text-slate-300 leading-relaxed">
                  Cortex supports hands-free activation via the phrase <strong>"Hey Cortex"</strong>. For strict privacy, detection runs 100% on your Mac using native local speech recognition. Continuous microphone audio is <strong>never uploaded to the cloud</strong>.
                </p>
              </div>

              <div className="flex items-center justify-between py-3 border-b border-white/5">
                <div>
                  <div className="font-semibold text-slate-200">Enable Hands-Free Wake Word</div>
                  <div className="text-[10px] text-slate-400">Activates listening when "Hey Cortex" is spoken</div>
                </div>
                <input
                  type="checkbox"
                  checked={wakeWordEnabled}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    if (setWakeWordEnabled) setWakeWordEnabled(checked);
                    updateSetting("wakeWordEnabled", checked);
                  }}
                  className="h-5 w-5 rounded accent-amber-500"
                />
              </div>

              <div className="space-y-2 py-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-200">Detection Sensitivity</span>
                  <span className="font-mono text-amber-300">
                    {Math.round((companionConfig.wakeWordSensitivity || 0.5) * 100)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="0.9"
                  step="0.1"
                  value={companionConfig.wakeWordSensitivity || 0.5}
                  onChange={(e) => updateSetting("wakeWordSensitivity", parseFloat(e.target.value))}
                  className="w-full accent-amber-500"
                />
                <div className="flex justify-between text-[9px] text-slate-500 font-mono">
                  <span>Fewer False Positives</span>
                  <span>More Sensitive</span>
                </div>
              </div>

              <div className="rounded-lg border border-white/5 bg-black/30 p-3 text-[11px] text-slate-400">
                <span className="font-semibold text-slate-300">Supported Activation Phrases:</span>
                <ul className="list-disc list-inside mt-1 space-y-0.5 text-slate-400">
                  <li>"Hey Cortex"</li>
                  <li>"Cortex"</li>
                  <li>"ಹೇ ಕಾರ್ಟೆಕ್ಸ್" (Kannada)</li>
                  <li>"सुनो कोर्टेक्स" (Hindi)</li>
                </ul>
              </div>
            </div>
          )}

          {/* TAB 4: MEMORY */}
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

          {/* TAB 5: MODEL */}
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
