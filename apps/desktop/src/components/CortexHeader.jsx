import React from "react";
import {
  Volume2, VolumeX, Maximize2, Minimize2,
  Sparkles, Languages, Moon, Sun, Minus, X
} from "lucide-react";

const LANG_OPTIONS = [
  { code: "auto", label: "Auto" },
  { code: "en", label: "English" },
  { code: "kn", label: "ಕನ್ನಡ" },
  { code: "hi", label: "हिन्दी" },
  { code: "ta", label: "தமிழ்" },
  { code: "te", label: "తెలుగు" },
];

export function CortexHeader({
  threadTitle,
  audioEnabled,
  onToggleAudio,
  preferredLang,
  onChangeLang,
  isFloating,
  onToggleFloating,
  theme,
  onToggleTheme,
  onHideWindow,
  trayStatus = "ready",
}) {
  const statusColors = {
    ready: "bg-emerald-500",
    listening: "bg-amber-400 animate-pulse",
    processing: "bg-blue-400 animate-pulse",
    speaking: "bg-emerald-400 animate-pulse",
    error: "bg-rose-500",
  };

  return (
    <header className="flex h-11 flex-shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 backdrop-blur-md select-none z-10">
      {/* Title & model badge */}
      <div className="flex items-center gap-2 min-w-0">
        <div className="flex items-center gap-1.5">
          <div className={`h-2 w-2 rounded-full ${statusColors[trayStatus] || "bg-emerald-500"}`} />
          <h1 className="truncate text-xs font-semibold text-[var(--text)] max-w-[160px] sm:max-w-[240px]">
            {isFloating ? (threadTitle || "Cortex Companion") : (threadTitle || "Cortex Assistant")}
          </h1>
        </div>

        {!isFloating && (
          <div className="hidden sm:flex items-center gap-1.5 rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent)] border border-[var(--border-2)]">
            <Sparkles className="h-3 w-3 text-[var(--accent)]" />
            <span>Gemini 3.5 Flash</span>
          </div>
        )}
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-1.5">
        {/* Language selector */}
        <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[10px] text-[var(--text)]">
          <Languages className="h-3 w-3 text-[var(--text-subtle)]" />
          <select
            value={preferredLang}
            onChange={(e) => onChangeLang(e.target.value)}
            className="bg-transparent text-[var(--text)] focus:outline-none cursor-pointer text-[10px]"
            title="Preferred Language"
          >
            {LANG_OPTIONS.map((opt) => (
              <option key={opt.code} value={opt.code} className="bg-[var(--surface)] text-[var(--text)]">
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* TTS Read-Aloud Toggle */}
        <button
          type="button"
          onClick={onToggleAudio}
          className={`flex h-7 w-7 items-center justify-center rounded-lg border transition-colors ${
            audioEnabled
              ? "bg-[var(--surface-2)] text-[var(--accent)] border-[var(--accent)]"
              : "bg-[var(--surface-2)] text-[var(--text-subtle)] border-[var(--border)] hover:text-[var(--text)]"
          }`}
          title={audioEnabled ? "Speech Output Enabled" : "Speech Output Muted"}
        >
          {audioEnabled ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5" />}
        </button>

        {/* Theme Toggle (standard mode only to save space in floating) */}
        {!isFloating && (
          <button
            type="button"
            onClick={onToggleTheme}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
            title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
          >
            {theme === "dark" ? <Sun className="h-3.5 w-3.5 text-[var(--accent)]" /> : <Moon className="h-3.5 w-3.5 text-[var(--accent)]" />}
          </button>
        )}

        {/* Window Mode Toggle: Floating Assistant vs Standard Workspace */}
        <button
          type="button"
          onClick={onToggleFloating}
          className={`flex h-7 items-center gap-1 rounded-lg border px-2 text-[10px] transition-colors ${
            isFloating
              ? "bg-[var(--surface-2)] text-[var(--accent)] border-[var(--accent)]"
              : "bg-[var(--surface-2)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text)]"
          }`}
          title={isFloating ? "Expand to Full Workspace" : "Switch to Floating Companion"}
        >
          {isFloating ? <Maximize2 className="h-3 w-3" /> : <Minimize2 className="h-3 w-3" />}
          <span className="hidden sm:inline font-medium">
            {isFloating ? "Expand" : "Float"}
          </span>
        </button>

        {/* Dismiss / Hide to Tray button in floating mode */}
        {isFloating && onHideWindow && (
          <button
            type="button"
            onClick={onHideWindow}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)] hover:bg-white/10 hover:text-[var(--text)] transition-colors"
            title="Hide to macOS Menu Bar (Esc)"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </header>
  );
}

export default CortexHeader;
