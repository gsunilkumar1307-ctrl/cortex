import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import { AssistantRuntimeProvider } from "@assistant-ui/react";

import { useCortexRuntime } from "./runtime/useCortexRuntime";
import cortexApi from "./runtime/cortexApi";
import { AudioRecorder } from "./runtime/audioRecorder";
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
  const [wakeWordEnabled, setWakeWordEnabled] = useState(false);
  const [theme, setTheme] = useState("dark");
  const [isFloating, setIsFloating] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [activeAudioStream, setActiveAudioStream] = useState(null);
  const [focusTrigger, setFocusTrigger] = useState(0);
  const [trayStatus, setTrayStatus] = useState("ready");

  // Audio & speech state refs
  const speechAudioRef = useRef(null);
  const audioRecorderRef = useRef(null);
  const wakeRecognizerRef = useRef(null);
  const companionConfigRef = useRef(null);

  // Sync tray status helper
  const setTrayStatusSafe = useCallback((status) => {
    setTrayStatus(status);
    if (cortexBridge?.setTrayStatus) {
      cortexBridge.setTrayStatus(status);
    }
  }, []);

  // Apply theme to DOM
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Load companion settings on startup
  useEffect(() => {
    if (cortexBridge?.getCompanionSettings) {
      cortexBridge.getCompanionSettings().then((cfg) => {
        if (cfg) {
          companionConfigRef.current = cfg;
          if ("wakeWordEnabled" in cfg) {
            setWakeWordEnabled(Boolean(cfg.wakeWordEnabled));
          }
        }
      }).catch(() => {});
    }
  }, []);

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
      } else if (type === "activate") {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(523.25, now);
        osc.frequency.exponentialRampToValueAtTime(659.25, now + 0.12);
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now);
        osc.stop(now + 0.2);
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

  // Read aloud / TTS implementation with instant stop
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
    setTrayStatusSafe("ready");
  }, [setTrayStatusSafe]);

  const speakText = useCallback((text, lang = "en") => {
    if (!audioEnabled || !text) return;
    stopSpeech();
    setIsSpeaking(true);
    setTrayStatusSafe("speaking");

    try {
      const url = cortexApi.getTtsUrl(text, lang, speakingRate);
      const audio = new Audio(url);
      speechAudioRef.current = audio;

      audio.onended = () => {
        setIsSpeaking(false);
        speechAudioRef.current = null;
        setTrayStatusSafe("ready");
      };
      audio.onerror = () => {
        // Fallback to Web Speech Synthesis if backend TTS fails
        if ("speechSynthesis" in window) {
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.rate = speakingRate;
          utterance.onend = () => {
            setIsSpeaking(false);
            setTrayStatusSafe("ready");
          };
          utterance.onerror = () => {
            setIsSpeaking(false);
            setTrayStatusSafe("ready");
          };
          window.speechSynthesis.speak(utterance);
        } else {
          setIsSpeaking(false);
          setTrayStatusSafe("ready");
        }
      };
      audio.play().catch(() => {
        setIsSpeaking(false);
        setTrayStatusSafe("ready");
      });
    } catch {
      setIsSpeaking(false);
      setTrayStatusSafe("ready");
    }
  }, [audioEnabled, speakingRate, stopSpeech, setTrayStatusSafe]);

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
          setTrayStatusSafe("processing");
        } else {
          cortexBridge.hideHud();
          if (!isSpeaking && !isListening) {
            setTrayStatusSafe("ready");
          }
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

  // Inbound Electron Events (Global Shortcut summon, Tray menu, Palette)
  useEffect(() => {
    if (!cortexBridge) return;

    const unsubFocus = cortexBridge.onFocusComposer?.(() => {
      setFocusTrigger((prev) => prev + 1);
    });
    const unsubVoice = cortexBridge.onStartVoiceInteraction?.(() => {
      handleToggleVoice();
    });
    const unsubNew = cortexBridge.onNewThread?.(() => {
      cortex.startNewThread();
      setFocusTrigger((prev) => prev + 1);
    });
    const unsubSettings = cortexBridge.onOpenSettings?.(() => {
      setSettingsOpen(true);
    });

    return () => {
      if (unsubFocus) unsubFocus();
      if (unsubVoice) unsubVoice();
      if (unsubNew) unsubNew();
      if (unsubSettings) unsubSettings();
    };
  }, []);

  // Keyboard shortcuts & Escape to hide
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
        } else if (isFloating && cortexBridge?.hideWindow) {
          cortexBridge.hideWindow();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSpeaking, stopSpeech, settingsOpen, auditOpen, cortex, isFloating]);

  // Voice Interaction: High-performance 16kHz WAV recording with fallback
  const handleToggleVoice = useCallback(async () => {
    if (isListening) {
      // User clicked stop, finish recording
      setIsListening(false);
      setTrayStatusSafe("processing");

      try {
        if (audioRecorderRef.current) {
          const wavBlob = await audioRecorderRef.current.stop();
          setActiveAudioStream(null);
          audioRecorderRef.current = null;

          if (wavBlob && wavBlob.size > 500) {
            const result = await cortexApi.audioChat(wavBlob);
            if (result && result.transcript) {
              cortex.onNew({ content: [{ type: "text", text: result.transcript }] });
            } else if (result && result.message) {
              speakText(result.message, preferredLang);
            }
          }
        }
      } catch (err) {
        console.warn("Audio recording processing notice:", err);
      } finally {
        if (!isSpeaking) setTrayStatusSafe("ready");
      }
    } else {
      // Start recording
      stopSpeech();
      try {
        const recorder = new AudioRecorder();
        audioRecorderRef.current = recorder;
        const stream = await recorder.start(companionConfigRef.current?.audioInputDevice);
        setActiveAudioStream(stream);
        setIsListening(true);
        setTrayStatusSafe("listening");
        playChime("activate");
      } catch (err) {
        console.warn("Audio recorder initialization notice:", err);
        // Fallback to Web Speech API
        if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
          const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
          const rec = new SpeechRec();
          rec.continuous = false;
          rec.interimResults = false;
          rec.lang = preferredLang === "auto" ? "en-US" : preferredLang;
          rec.onstart = () => {
            setIsListening(true);
            setTrayStatusSafe("listening");
          };
          rec.onend = () => {
            setIsListening(false);
            setTrayStatusSafe("ready");
          };
          rec.onerror = () => {
            setIsListening(false);
            setTrayStatusSafe("ready");
          };
          rec.onresult = (e) => {
            const transcript = e.results[0]?.[0]?.transcript || "";
            if (transcript) {
              cortex.onNew({ content: [{ type: "text", text: transcript }] });
            }
          };
          rec.start();
        } else {
          alert("Microphone permission or audio capture failed: " + err.message);
        }
      }
    }
  }, [isListening, isSpeaking, stopSpeech, setTrayStatusSafe, playChime, cortex, preferredLang, speakText]);

  // On-Device Wake-Word Detection ("Hey Cortex")
  useEffect(() => {
    if (!wakeWordEnabled) {
      if (wakeRecognizerRef.current) {
        try { wakeRecognizerRef.current.abort(); } catch {}
        wakeRecognizerRef.current = null;
      }
      return;
    }

    if (isListening || isSpeaking) return;
    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) return;

    let isCleanedUp = false;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SpeechRec();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    wakeRecognizerRef.current = rec;

    rec.onresult = (e) => {
      if (isCleanedUp) return;
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const text = (e.results[i][0]?.transcript || "").toLowerCase().trim();
        if (
          text.includes("hey cortex") ||
          text.includes("cortex") ||
          text.includes("kortek") ||
          text.includes("core tech")
        ) {
          playChime("wake");
          try { rec.abort(); } catch {}
          if (cortexBridge?.focusWindow) {
            cortexBridge.focusWindow();
          }
          handleToggleVoice();
          break;
        }
      }
    };

    rec.onerror = (err) => {
      if (!isCleanedUp && wakeWordEnabled && err.error !== "not-allowed") {
        setTimeout(() => {
          if (!isCleanedUp && wakeWordEnabled) {
            try { rec.start(); } catch {}
          }
        }, 1500);
      }
    };

    rec.onend = () => {
      if (!isCleanedUp && wakeWordEnabled && !isListening && !isSpeaking) {
        setTimeout(() => {
          if (!isCleanedUp && wakeWordEnabled) {
            try { rec.start(); } catch {}
          }
        }, 800);
      }
    };

    try {
      rec.start();
    } catch {}

    return () => {
      isCleanedUp = true;
      try { rec.abort(); } catch {}
      wakeRecognizerRef.current = null;
    };
  }, [wakeWordEnabled, isListening, isSpeaking, playChime, handleToggleVoice]);

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
            onHideWindow={() => cortexBridge?.hideWindow?.()}
            trayStatus={trayStatus}
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
          <div className="p-3 bg-gradient-to-t from-[var(--bg)] via-[var(--bg)]/90 to-transparent">
            <CortexComposer
              onSend={(text) => cortex.onNew({ content: [{ type: "text", text }] })}
              onStop={cortex.onCancel}
              isRunning={cortex.isRunning}
              onOpenSettings={() => setSettingsOpen(true)}
              onOpenAudit={() => setAuditOpen(true)}
              onNewThread={cortex.startNewThread}
              onAudioDictate={handleToggleVoice}
              isListening={isListening}
              activeAudioStream={activeAudioStream}
              isSpeaking={isSpeaking}
              onStopSpeech={stopSpeech}
              focusTrigger={focusTrigger}
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
          onPlayChime={playChime}
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
