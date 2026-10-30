import { app, BrowserWindow, ipcMain, globalShortcut, session, systemPreferences, screen, shell } from "electron";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const preloadPath = path.join(__dirname, "preload.cjs");

let mainWin = null;
let hudWin = null;
let isFloatingMode = false;
let standardBounds = { width: 1120, height: 760, x: undefined, y: undefined };

function getSessionSecret() {
  if (process.env.CORTEX_SESSION_SECRET) {
    return process.env.CORTEX_SESSION_SECRET.trim();
  }
  try {
    const rootDir = path.resolve(__dirname, "../../..");
    const secretFile = path.join(rootDir, ".session_secret");
    if (fs.existsSync(secretFile)) {
      return fs.readFileSync(secretFile, "utf-8").trim();
    }
  } catch (err) {
    console.warn("[electron] Could not read .session_secret:", err);
  }
  return "";
}

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
    minWidth: 400,
    minHeight: 520,
    title: "Cortex",
    backgroundColor: "#00000000",
    transparent: true,
    vibrancy: "under-window",
    visualEffectState: "active",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      preload: preloadPath,
    },
  });

  mainWin.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://127.0.0.1:5173") || url.startsWith("http://localhost:5173")) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWin.loadURL(process.env.CORTEX_DESKTOP_URL || "http://127.0.0.1:5173");

  mainWin.on("close", () => {
    mainWin = null;
  });
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
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      preload: preloadPath,
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

  // Attach session token automatically to backend requests without exposing it to the renderer
  const sessionSecret = getSessionSecret();
  if (sessionSecret && session.defaultSession) {
    const authorizedOrigin = (process.env.CORTEX_API_ORIGIN || "http://127.0.0.1:8765").replace(/\/+$/, "");
    const allowedFilter = [
      `${authorizedOrigin}/*`,
      "http://127.0.0.1:8765/*",
      "http://localhost:8765/*",
    ];
    session.defaultSession.webRequest.onBeforeSendHeaders(
      { urls: allowedFilter },
      (details, callback) => {
        try {
          const reqUrl = new URL(details.url);
          // Strict origin validation: prevent leaking token across redirect or alternate port/host
          if (
            reqUrl.origin === authorizedOrigin ||
            reqUrl.origin === "http://127.0.0.1:8765" ||
            reqUrl.origin === "http://localhost:8765"
          ) {
            details.requestHeaders["X-Cortex-Session"] = sessionSecret;
          }
        } catch (err) {
          console.warn("[electron] Invalid request URL in onBeforeSendHeaders:", err);
        }
        callback({ requestHeaders: details.requestHeaders });
      }
    );
  }

  createMainWindow();
  createHudWindow();

  // Global shortcut: ⌘K or Ctrl+K to toggle command palette
  globalShortcut.register("CommandOrControl+K", () => {
    if (mainWin) {
      mainWin.webContents.send("toggle-palette");
      if (!mainWin.isFocused()) mainWin.focus();
    }
  });

  // Global shortcut: Option+Space (or Alt+Space) to summon/dismiss Cortex from anywhere
  try {
    globalShortcut.register("Alt+Space", () => {
      if (mainWin) {
        if (mainWin.isVisible() && mainWin.isFocused()) {
          mainWin.hide();
        } else {
          mainWin.show();
          mainWin.focus();
        }
      }
    });
  } catch (err) {
    console.warn("[electron] Could not register Alt+Space global shortcut:", err);
  }
});

// ─── Floating Assistant Mode Controls ──────────────────────────────────────────
ipcMain.on("set-window-mode", (event, mode) => {
  if (!mainWin) return;
  if (mode === "floating") {
    if (!isFloatingMode) {
      standardBounds = mainWin.getBounds();
    }
    isFloatingMode = true;
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width: screenWidth, height: screenHeight } = primaryDisplay.workAreaSize;
    const floatWidth = 430;
    const floatHeight = Math.min(720, screenHeight - 64);
    
    mainWin.setAlwaysOnTop(true, "floating");
    mainWin.setBounds({
      x: Math.max(0, screenWidth - floatWidth - 24),
      y: 48,
      width: floatWidth,
      height: floatHeight,
    });
    mainWin.webContents.send("window-mode-changed", "floating");
  } else {
    isFloatingMode = false;
    mainWin.setAlwaysOnTop(false);
    if (standardBounds.width && standardBounds.height) {
      mainWin.setBounds(standardBounds);
    } else {
      mainWin.setSize(1120, 760);
      mainWin.center();
    }
    mainWin.webContents.send("window-mode-changed", "standard");
  }
});

ipcMain.handle("get-window-mode", () => {
  return isFloatingMode ? "floating" : "standard";
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
