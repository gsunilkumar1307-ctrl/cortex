import { app, BrowserWindow, ipcMain, globalShortcut, session, systemPreferences } from "electron";

let mainWin = null;
let hudWin = null;

function setupPermissions() {
  if (process.platform === "darwin") {
    try {
      systemPreferences.askForMediaAccess("microphone").then((granted) => {
        console.log("[electron] Microphone access granted:", granted);
      });
    } catch (err) {
      console.warn("[electron] Could not request mic access:", err);
    }
  }

  if (session.defaultSession) {
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
      const allowed = ["media", "microphone", "camera", "notifications", "screen"];
      callback(allowed.includes(permission));
    });
    session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
      return true;
    });
  }
}

function createMainWindow() {
  mainWin = new BrowserWindow({
    width: 1120,
    height: 760,
    minWidth: 720,
    minHeight: 560,
    title: "Cortex",
    backgroundColor: "#00000000",
    transparent: true,
    vibrancy: "under-window",
    visualEffectState: "active",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      contextIsolation: false,
    },
  });

  mainWin.loadURL(process.env.CORTEX_DESKTOP_URL || "http://127.0.0.1:5173");
}

function createHudWindow() {
  hudWin = new BrowserWindow({
    width: 440,
    height: 220,
    x: 20,
    y: 40,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: false,
    hasShadow: false,
    webPreferences: {
      contextIsolation: false,
    },
  });

  hudWin.loadURL(
    (process.env.CORTEX_DESKTOP_URL || "http://127.0.0.1:5173") + "#hud"
  );
  hudWin.setIgnoreMouseEvents(true, { forward: true });
  hudWin.hide();
}

app.whenReady().then(() => {
  setupPermissions();
  createMainWindow();
  createHudWindow();

  // Global shortcut: ⌘K or Ctrl+K to toggle command palette
  globalShortcut.register("CommandOrControl+K", () => {
    if (mainWin) {
      mainWin.webContents.send("toggle-palette");
      if (!mainWin.isFocused()) mainWin.focus();
    }
  });
});

// HUD IPC bridge
ipcMain.on("hud-show", (_, data) => {
  if (!hudWin) return;
  hudWin.webContents.send("hud-update", data);
  hudWin.show();
});

ipcMain.on("hud-hide", () => {
  if (hudWin) hudWin.hide();
});

app.on("window-all-closed", () => {
  globalShortcut.unregisterAll();
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
    createHudWindow();
  }
});
