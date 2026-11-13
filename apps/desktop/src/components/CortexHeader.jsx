import React from "react";
import {
  Volume2, VolumeX, AppWindow, PanelRightClose,
  Sparkles, Shield, Languages, Moon, Sun, Download
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
  onExportMarkdown,
}) {
  return (
    <header className="flex h-13 items-center justify-between border-b border-white/10 bg-black/30 px-4 py-2 backdrop-blur-md select-none">
      {/* Title & model badge */}
      <div className="flex items-center gap-3 min-w-0">
        <h1 className="truncate text-xs font-semibold text-slate-100 max-w-[280px]">
          {threadTitle || "Cortex Assistant"}
        </h1>

        <div className="hidden sm:flex items-center gap-1.5 rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-300 border border-indigo-500/20">
          <Sparkles className="h-3 w-3 text-indigo-400" />
          <span>Gemini 3.5 Flash</span>
        </div>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-2">
        {/* Language selector */}
        <div className="flex items-center gap-1 rounded-lg border border-white/5 bg-white/5 px-2 py-1 text-[11px] text-slate-300">
          <Languages className="h-3.5 w-3.5 text-slate-400" />
          <select
            value={preferredLang}
            onChange={(e) => onChangeLang(e.target.value)}
            className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
          >
            {LANG_OPTIONS.map((opt) => (
              <option key={opt.code} value={opt.code} className="bg-slate-900 text-white">
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* TTS Read-Aloud Toggle */}
        <button
          type="button"
          onClick={onToggleAudio}
          className={`flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 transition-colors ${
            audioEnabled
              ? "bg-indigo-600/30 text-indigo-300 border-indigo-500/30"
              : "bg-white/5 text-slate-400 hover:text-white"
          }`}
          title={audioEnabled ? "Speech Output Enabled" : "Speech Output Muted"}
        >
          {audioEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
        </button>

        {/* Theme Toggle */}
        <button
          type="button"
          onClick={onToggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 bg-white/5 text-slate-400 hover:text-white transition-colors"
          title={`Switch to ${theme === "dark" ? "Light" : "Dark"} Mode`}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>

        {/* Window Mode Toggle: Floating Assistant vs Standard Workspace */}
        <button
          type="button"
          onClick={onToggleFloating}
          className={`flex h-8 items-center gap-1.5 rounded-lg border border-white/5 px-2.5 text-xs transition-colors ${
            isFloating
              ? "bg-sky-600/30 text-sky-200 border-sky-500/40"
              : "bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white"
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

