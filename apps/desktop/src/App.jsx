import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { AssistantRuntimeProvider } from "@assistant-ui/react";

import { useCortexRuntime } from "./runtime/useCortexRuntime";
import cortexApi from "./runtime/cortexApi";
import CortexSidebar from "./components/CortexSidebar";
import CortexHeader from "./components/CortexHeader";
import CortexThread from "./components/CortexThread";
import CortexComposer from "./components/CortexComposer";
import SettingsModal from "./components/modals/SettingsModal";
import AuditModal from "./components/modals/AuditModal";
import "./styles.css";

// Electron IPC bridge
const cortexBridge = typeof window !== "undefined" && window.cortexAPI ? window.cortexAPI : null;

export function App() {
  const [preferredLang, setPreferredLang] = useState("auto");
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [speakingRate, setSpeakingRate] = useState(1.0);
  const [chimesEnabled, setChimesEnabled] = useState(true);
  const [wakeWordEnabled, setWakeWordEnabled] = useState(true);
  const [theme, setTheme] = useState("dark");
  const [isFloating, setIsFloating] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isListening, setIsListening] = useState(false);

  // Audio & speech state refs
  const audioCtxRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const processorRef = useRef(null);
  const audioChunksRef = useRef([]);
  const speechAudioRef = useRef(null);
  const wakeRecognizerRef = useRef(null);

  // Apply theme to DOM
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Audio chime player
  const playChime = useCallback((type = "activate") => {
    if (!chimesEnabled) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      if (type === "wake") {
        [783.99, 1046.5].forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, now + idx * 0.08);
          gain.gain.setValueAtTime(0, now + idx * 0.08);
          gain.gain.linearRampToValueAtTime(0.12, now + idx * 0.08 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.26);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.08);
          osc.stop(now + idx * 0.08 + 0.28);
        });
      } else if (type === "alert") {
        [440, 554.37].forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "triangle";
          osc.frequency.setValueAtTime(freq, now + idx * 0.1);
          gain.gain.setValueAtTime(0.08, now + idx * 0.1);
          gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.1 + 0.16);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.1);
          osc.stop(now + idx * 0.1 + 0.18);
        });
      } else if (type === "success") {
        [587.33, 880.0].forEach((freq) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, now);
          gain.gain.setValueAtTime(0.1, now);
          gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now);
          osc.stop(now + 0.34);
        });
      }
    } catch {}
  }, [chimesEnabled]);

  // Read aloud / TTS implementation
  const stopSpeech = useCallback(() => {
    if (speechAudioRef.current) {
      try {
        speechAudioRef.current.pause();
        speechAudioRef.current = null;
      } catch {}
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {}
    }
    setIsSpeaking(false);
  }, []);

  const speakText = useCallback((text, lang = "en") => {
    if (!audioEnabled || !text) return;
    stopSpeech();
    setIsSpeaking(true);

    try {
      const url = cortexApi.getTtsUrl(text, lang, speakingRate);
      const audio = new Audio(url);
      speechAudioRef.current = audio;

      audio.onended = () => {
        setIsSpeaking(false);
        speechAudioRef.current = null;
      };
      audio.onerror = () => {
        // Fallback to Web Speech Synthesis if backend TTS fails
        if ("speechSynthesis" in window) {
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.rate = speakingRate;
          utterance.onend = () => setIsSpeaking(false);
          utterance.onerror = () => setIsSpeaking(false);
          window.speechSynthesis.speak(utterance);
        } else {
          setIsSpeaking(false);
        }
      };
      audio.play().catch(() => {
        setIsSpeaking(false);
      });
    } catch {
      setIsSpeaking(false);
    }
  }, [audioEnabled, speakingRate, stopSpeech]);

  // Hook into Cortex Custom Runtime
  const cortex = useCortexRuntime({
    preferredLanguage: preferredLang,
    onAudioPlay: (text, lang) => {
      speakText(text, lang);
    },
    onTaskChange: (task) => {
      // Sync with Electron Heads-Up Display (HUD)
      if (cortexBridge) {
        if (task && ["running", "executing"].includes(task.status)) {
          cortexBridge.showHud({ intent: task.intent, steps: task.auditTrail });
        } else {
          cortexBridge.hideHud();
        }
      }
      if (task?.status === "waiting_approval") {
        playChime("alert");
      } else if (task?.status === "completed") {
        playChime("success");
      }
    },
  });

  // Toggle Window Mode (Standard Workspace vs Floating Mode)
  useEffect(() => {
    if (cortexBridge) {
      const unsub = cortexBridge.onWindowModeChanged((mode) => setIsFloating(mode === "floating"));
      cortexBridge.getWindowMode().then((mode) => {
        if (mode === "floating") setIsFloating(true);
      }).catch(() => {});
      return () => {
        if (unsub) unsub();
      };
    }
  }, []);

  const handleToggleFloating = () => {
    const next = !isFloating;
    setIsFloating(next);
    if (cortexBridge) {
      cortexBridge.setWindowMode(next ? "floating" : "standard");
    }
  };

  // Keyboard shortcuts
  useEffect(() => {
    function onKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === "n") {
        e.preventDefault();
        cortex.startNewThread();
      } else if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        setSettingsOpen(true);
      } else if (e.key === "Escape") {
        if (isSpeaking) {
          stopSpeech();
        } else if (settingsOpen) {
          setSettingsOpen(false);
        } else if (auditOpen) {
          setAuditOpen(false);
        } else if (cortex.isRunning) {
          cortex.onCancel();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSpeaking, stopSpeech, settingsOpen, auditOpen, cortex]);

  // Voice dictation in composer
  const handleToggleDictation = () => {
    if (isListening) {
      // Stop recording
      setIsListening(false);
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
        mediaStreamRef.current = null;
      }
    } else {
      // Start Web Speech or audio capture
      if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        const rec = new SpeechRec();
        rec.continuous = false;
        rec.interimResults = false;
        rec.lang = preferredLang === "auto" ? "en-US" : preferredLang;
        rec.onstart = () => setIsListening(true);
        rec.onend = () => setIsListening(false);
        rec.onerror = () => setIsListening(false);
        rec.onresult = (e) => {
          const transcript = e.results[0]?.[0]?.transcript || "";
          if (transcript) {
            cortex.onNew({ content: [{ type: "text", text: transcript }] });
          }
        };
        rec.start();
      } else {
        alert("Speech recognition is not supported in this browser window.");
      }
    }
  };

  // Task Actions (Approve, Deny, Edit Draft)
  const handleApproveTask = async (taskId, approvalHash) => {
    try {
      const res = await cortexApi.approveTask(taskId, true, approvalHash);
      if (res.task) {
        cortex.setActiveTask(res.task);
      }
      cortex.refreshThreads();
    } catch (err) {
      alert("Approval error: " + err.message);
    }
  };

  const handleCancelTask = async (taskId) => {
    try {
      const res = await cortexApi.approveTask(taskId, false, null);
      if (res.task) {
        cortex.setActiveTask(res.task);
      }
      cortex.refreshThreads();
    } catch {
      await cortexApi.cancelTask(taskId);
      cortex.refreshThreads();
    }
  };

  const handleEditDraft = async (taskId, draftData) => {
    try {
      const res = await cortexApi.editDraft(taskId, draftData);
      if (res.task) {
        cortex.setActiveTask(res.task);
      }
      cortex.refreshThreads();
    } catch (err) {
      alert("Edit draft error: " + err.message);
    }
  };

  // Export current conversation to Markdown
  const handleExportMarkdown = () => {
    if (cortex.messages.length === 0) return;
    let md = `# ${cortex.threadTitle}\n*Exported from Cortex on ${new Date().toLocaleString()}*\n\n---\n\n`;
    for (const m of cortex.messages) {
      const role = m.role === "user" ? "### User" : "### Cortex";
      let text = "";
      if (typeof m.content === "string") text = m.content;
      else if (Array.isArray(m.content)) {
        text = m.content.map((c) => c.text || "").join("\n");
      }
      md += `${role}\n\n${text}\n\n---\n\n`;
    }

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${cortex.threadTitle.replace(/[^a-zA-Z0-9_-]/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <AssistantRuntimeProvider runtime={cortex.runtime}>
      <div className="flex h-screen w-screen overflow-hidden bg-[var(--bg)] font-sans text-[var(--text)] antialiased select-none">
        {/* Left Sidebar (Desktop Workspace View) */}
        {!isFloating && (
          <CortexSidebar
            threads={cortex.threads}
            activeThreadId={cortex.threadId}
            onSelectThread={cortex.loadThread}
            onNewThread={cortex.startNewThread}
            onDeleteThread={cortex.deleteThread}
            onRenameThread={cortex.renameThread}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenAudit={() => setAuditOpen(true)}
            onExportMarkdown={handleExportMarkdown}
            isCollapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          />
        )}

        {/* Main Conversation Area */}
        <div className="flex flex-1 flex-col h-full min-w-0 overflow-hidden bg-[var(--bg)]">
          {/* Header */}
          <CortexHeader
            threadTitle={cortex.threadTitle}
            audioEnabled={audioEnabled}
            onToggleAudio={() => setAudioEnabled((a) => !a)}
            preferredLang={preferredLang}
            onChangeLang={setPreferredLang}
            isFloating={isFloating}
            onToggleFloating={handleToggleFloating}
            theme={theme}
            onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            onExportMarkdown={handleExportMarkdown}
          />

          {/* Messages Thread */}
          <CortexThread
            messages={cortex.messages}
            isRunning={cortex.isRunning}
            onEditMessage={cortex.onEdit}
            onReload={cortex.onReload}
            onApproveTask={handleApproveTask}
            onCancelTask={handleCancelTask}
            onEditDraft={handleEditDraft}
            onSelectPrompt={(prompt) => cortex.onNew({ content: [{ type: "text", text: prompt }] })}
            onSpeakText={speakText}
            isSpeaking={isSpeaking}
            onStopSpeech={stopSpeech}
            theme={theme}
          />

          {/* Composer Footer */}
          <div className="p-4 bg-gradient-to-t from-[var(--bg)] via-[var(--bg)]/90 to-transparent">
            <CortexComposer
              onSend={(text) => cortex.onNew({ content: [{ type: "text", text }] })}
              onStop={cortex.onCancel}
              isRunning={cortex.isRunning}
              onOpenSettings={() => setSettingsOpen(true)}
              onOpenAudit={() => setAuditOpen(true)}
              onNewThread={cortex.startNewThread}
              onAudioDictate={handleToggleDictation}
              isListening={isListening}
            />
          </div>
        </div>

        {/* Settings Modal */}
        <SettingsModal
          isOpen={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          speakingRate={speakingRate}
          setSpeakingRate={setSpeakingRate}
          chimesEnabled={chimesEnabled}
          setChimesEnabled={setChimesEnabled}
          wakeWordEnabled={wakeWordEnabled}
          setWakeWordEnabled={setWakeWordEnabled}
          onClearHistory={() => {
            cortexApi.clearMemories("history");
            cortex.startNewThread();
          }}
        />

        {/* Audit Modal */}
        <AuditModal
          isOpen={auditOpen}
          onClose={() => setAuditOpen(false)}
        />
      </div>
    </AssistantRuntimeProvider>
  );
}

// Mount React Root
const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<App />);
}
export default App;
