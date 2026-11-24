const { contextBridge, ipcRenderer } = require("electron");

// Secure, minimal Electron-to-Renderer bridge
// Renderer cannot access Node.js filesystem, shell, child_process, or raw IPC
contextBridge.exposeInMainWorld("cortexAPI", {
  showHud: (data) => ipcRenderer.send("hud-show", data),
  hideHud: () => ipcRenderer.send("hud-hide"),
  onWindowModeChanged: (callback) => {
    const listener = (event, mode) => callback(mode);
    ipcRenderer.on("window-mode-changed", listener);
    return () => ipcRenderer.removeListener("window-mode-changed", listener);
  },
  getWindowMode: () => ipcRenderer.invoke("get-window-mode"),
  setWindowMode: (mode) => ipcRenderer.send("set-window-mode", mode),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
});
