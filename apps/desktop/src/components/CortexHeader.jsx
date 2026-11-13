import React from "react";
import {
  Volume2, VolumeX, AppWindow,
  Sparkles, Languages, Moon, Sun
} from "lucide-react";

const LANG_OPTIONS = [
  { code: "auto", label: "Auto Detect" },
  { code: "en", label: "English" },
  { code: "kn", label: "ಕನ್ನಡ (Kannada)" },
  { code: "hi", label: "हिन्दी (Hindi)" },
  { code: "ta", label: "தமிழ் (Tamil)" },
  { code: "te", label: "తెలుగు (Telugu)" },
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
}) {
  return (
    <header className="flex h-13 flex-shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-4 py-2 backdrop-blur-md select-none z-10">
      {/* Title & model badge */}
      <div className="flex items-center gap-3 min-w-0">
        <h1 className="truncate text-xs font-semibold text-[var(--text)] max-w-[280px]">
          {threadTitle || "Cortex Assistant"}
        </h1>

        <div className="hidden sm:flex items-center gap-1.5 rounded-full bg-[var(--surface-2)] px-2.5 py-0.5 text-[10px] font-medium text-[var(--accent)] border border-[var(--border-2)]">
          <Sparkles className="h-3 w-3 text-[var(--accent)]" />
          <span>Gemini 3.5 Flash</span>
        </div>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-2">
        {/* Language selector */}
        <div className="flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-[11px] text-[var(--text)]">
          <Languages className="h-3.5 w-3.5 text-[var(--text-subtle)]" />
          <select
            value={preferredLang}
            onChange={(e) => onChangeLang(e.target.value)}
            className="bg-transparent text-[var(--text)] focus:outline-none cursor-pointer text-[11px]"
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
          className={`flex h-8 w-8 items-center justify-center rounded-lg border transition-colors ${
            audioEnabled
              ? "bg-[var(--surface-2)] text-[var(--accent)] border-[var(--accent)]"
              : "bg-[var(--surface-2)] text-[var(--text-subtle)] border-[var(--border)] hover:text-[var(--text)]"
          }`}
          title={audioEnabled ? "Speech Output Enabled" : "Speech Output Muted"}
        >
          {audioEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
        </button>

        {/* Theme Toggle */}
        <button
          type="button"
          onClick={onToggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
        >
          {theme === "dark" ? <Sun className="h-4 w-4 text-[var(--accent)]" /> : <Moon className="h-4 w-4 text-[var(--accent)]" />}
        </button>

        {/* Window Mode Toggle: Floating Assistant vs Standard Workspace */}
        <button
          type="button"
          onClick={onToggleFloating}
          className={`flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs transition-colors ${
            isFloating
              ? "bg-[var(--surface-2)] text-[var(--accent)] border-[var(--accent)]"
              : "bg-[var(--surface-2)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text)]"
          }`}
          title={isFloating ? "Switch to Full Workspace" : "Switch to Floating Assistant"}
        >
          <AppWindow className="h-3.5 w-3.5" />
          <span className="hidden md:inline text-[11px] font-medium">
            {isFloating ? "Standard View" : "Floating Mode"}
          </span>
        </button>
      </div>
    </header>
  );
}
export default CortexHeader;
