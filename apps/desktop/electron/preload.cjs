const { contextBridge, ipcRenderer } = require("electron");

// Secure, minimal Electron-to-Renderer bridge
// Renderer cannot access Node.js filesystem, shell, child_process, or raw IPC
contextBridge.exposeInMainWorld("cortexAPI", {
  // HUD
  showHud: (data) => ipcRenderer.send("hud-show", data),
  hideHud: () => ipcRenderer.send("hud-hide"),

  // Window Mode & State
  getWindowMode: () => ipcRenderer.invoke("get-window-mode"),
  setWindowMode: (mode) => ipcRenderer.send("set-window-mode", mode),
  onWindowModeChanged: (callback) => {
    const listener = (event, mode) => callback(mode);
    ipcRenderer.on("window-mode-changed", listener);
    return () => ipcRenderer.removeListener("window-mode-changed", listener);
  },
  hideWindow: () => ipcRenderer.send("hide-window"),
  focusWindow: () => ipcRenderer.send("focus-window"),

  // Desktop Companion Settings & Global Shortcuts
  getCompanionSettings: () => ipcRenderer.invoke("get-companion-settings"),
  updateCompanionSettings: (settings) => ipcRenderer.invoke("update-companion-settings", settings),
  setGlobalShortcut: (shortcut) => ipcRenderer.invoke("set-global-shortcut", shortcut),

  // System Tray Status Synchronization
  setTrayStatus: (status) => ipcRenderer.send("set-tray-status", status),

  // Inbound Action Notifications from Electron / Tray / Global Shortcuts
  onFocusComposer: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("focus-composer", listener);
    return () => ipcRenderer.removeListener("focus-composer", listener);
  },
  onStartVoiceInteraction: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("start-voice-interaction", listener);
    return () => ipcRenderer.removeListener("start-voice-interaction", listener);
  },
  onNewThread: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("new-thread", listener);
    return () => ipcRenderer.removeListener("new-thread", listener);
  },
  onOpenSettings: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("open-settings", listener);
    return () => ipcRenderer.removeListener("open-settings", listener);
  },
  onTogglePalette: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("toggle-palette", listener);
    return () => ipcRenderer.removeListener("toggle-palette", listener);
  },
});
