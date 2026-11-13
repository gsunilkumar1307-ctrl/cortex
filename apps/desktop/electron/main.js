import { createRequire } from "module";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const require = createRequire(import.meta.url);
const {
  app,
  BrowserWindow,
  ipcMain,
  globalShortcut,
  session,
  systemPreferences,
  screen,
  shell,
  Tray,
  Menu,
  nativeImage,
} = require("electron");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const preloadPath = path.join(__dirname, "preload.cjs");

let mainWin = null;
let hudWin = null;
let tray = null;
let isQuitting = false;
let isFloatingMode = false;
let currentRegisteredShortcut = null;
let trayCurrentStatus = "ready";

// ─── Default Companion Settings ───────────────────────────────────────────────
const DEFAULT_SETTINGS = {
  globalShortcut: process.platform === "darwin" ? "Command+Shift+A" : "Control+Shift+A",
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
  floatingBounds: { width: 440, height: 720 },
  standardBounds: { width: 1120, height: 760 },
};

function getSettingsFilePath() {
  try {
    return path.join(app.getPath("userData"), "cortex-desktop-settings.json");
  } catch {
    return path.join(__dirname, "../../..", "cortex-desktop-settings.json");
  }
}

function loadSettings() {
  const filePath = getSettingsFilePath();
  try {
    if (fs.existsSync(filePath)) {
      const data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      return { ...DEFAULT_SETTINGS, ...data };
    }
  } catch (err) {
    console.warn("[electron] Error loading settings:", err);
  }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(settings) {
  const filePath = getSettingsFilePath();
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(settings, null, 2), "utf-8");
  } catch (err) {
    console.warn("[electron] Error saving settings:", err);
  }
}

let companionSettings = loadSettings();

// ─── Session Secret Authentication Header Injection ───────────────────────────
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
    session.defaultSession.setPermissionCheckHandler(() => true);
  }
}

// ─── Multi-Monitor Display Helper ─────────────────────────────────────────────
function getActiveDisplay() {
  try {
    const cursorPoint = screen.getCursorScreenPoint();
    return screen.getDisplayNearestPoint(cursorPoint) || screen.getPrimaryDisplay();
  } catch {
    return screen.getPrimaryDisplay();
  }
}

function computeFloatingPosition(display, width, height) {
  const workArea = display.workArea;
  const x = Math.max(workArea.x, workArea.x + workArea.width - width - 24);
  const y = Math.max(workArea.y, workArea.y + 48);
  return { x, y };
}

// ─── Create Main Companion Window ─────────────────────────────────────────────
function createMainWindow() {
  const display = getActiveDisplay();
  const initBounds = isFloatingMode
    ? companionSettings.floatingBounds || { width: 440, height: 720 }
    : companionSettings.standardBounds || { width: 1120, height: 760 };

  mainWin = new BrowserWindow({
    width: initBounds.width || 1120,
    height: initBounds.height || 760,
    x: initBounds.x,
    y: initBounds.y,
    minWidth: 380,
    minHeight: 480,
    title: "Cortex",
    backgroundColor: "#00000000",
    transparent: true,
    vibrancy: "under-window",
    visualEffectState: "active",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    alwaysOnTop: isFloatingMode ? Boolean(companionSettings.alwaysOnTop) : false,
    show: !companionSettings.startMinimized,
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

  // Non-destructive Close: Hides window on red traffic light instead of killing the app
  mainWin.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWin.hide();
      return false;
    }
  });

  // Track size/position changes for persistence
  mainWin.on("resize", () => {
    if (!companionSettings.rememberBounds || !mainWin) return;
    const bounds = mainWin.getBounds();
    if (isFloatingMode) {
      companionSettings.floatingBounds = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y };
    } else {
      companionSettings.standardBounds = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y };
    }
    saveSettings(companionSettings);
  });

  mainWin.on("move", () => {
    if (!companionSettings.rememberBounds || !mainWin) return;
    const bounds = mainWin.getBounds();
    if (isFloatingMode) {
      companionSettings.floatingBounds = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y };
    } else {
      companionSettings.standardBounds = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y };
    }
    saveSettings(companionSettings);
  });

  // Close on Blur: Optional companion behavior
  mainWin.on("blur", () => {
    if (isFloatingMode && companionSettings.closeOnBlur && mainWin && mainWin.isVisible()) {
      mainWin.hide();
    }
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

  hudWin.loadURL((process.env.CORTEX_DESKTOP_URL || "http://127.0.0.1:5173") + "#hud");
  hudWin.setIgnoreMouseEvents(true, { forward: true });
  hudWin.hide();
}

// ─── Global Shortcut Management (P0 & P1) ─────────────────────────────────────
function summonOrToggleCortex() {
  if (!mainWin) {
    createMainWindow();
    return;
  }

  if (mainWin.isVisible() && mainWin.isFocused()) {
    // If user presses shortcut while already focused, toggle hide
    mainWin.hide();
  } else {
    // If in floating mode, re-align with current active monitor if bounds aren't pinned
    if (isFloatingMode) {
      const display = getActiveDisplay();
      const currentBounds = mainWin.getBounds();
      // Ensure window is on the active screen
      const work = display.workArea;
      if (
        currentBounds.x < work.x ||
        currentBounds.x > work.x + work.width ||
        currentBounds.y < work.y ||
        currentBounds.y > work.y + work.height
      ) {
        const { x, y } = computeFloatingPosition(display, currentBounds.width, currentBounds.height);
        mainWin.setPosition(x, y);
      }
    }

    if (mainWin.isMinimized()) mainWin.restore();
    mainWin.show();
    mainWin.focus();
    if (process.platform === "darwin") {
      app.focus({ steal: true });
    }
    mainWin.webContents.send("focus-composer");
  }
}

function registerGlobalSummonShortcut(shortcutString) {
  if (!shortcutString || typeof shortcutString !== "string" || !shortcutString.trim()) {
    if (currentRegisteredShortcut) {
      globalShortcut.unregister(currentRegisteredShortcut);
      currentRegisteredShortcut = null;
    }
    return { success: true, shortcut: "" };
  }

  const cleaned = shortcutString.trim();

  // Unregister existing shortcut before registering new one
  if (currentRegisteredShortcut) {
    try {
      globalShortcut.unregister(currentRegisteredShortcut);
    } catch (err) {
      console.warn("[electron] Error unregistering previous shortcut:", err);
    }
  }

  try {
    const registered = globalShortcut.register(cleaned, () => {
      summonOrToggleCortex();
    });

    if (registered) {
      currentRegisteredShortcut = cleaned;
      console.log(`[electron] Global shortcut registered: ${cleaned}`);
      return { success: true, shortcut: cleaned };
    } else {
      console.warn(`[electron] Failed to register global shortcut: ${cleaned}`);
      // Fallback: try restoring default if custom failed
      if (cleaned !== DEFAULT_SETTINGS.globalShortcut) {
        const fallback = globalShortcut.register(DEFAULT_SETTINGS.globalShortcut, summonOrToggleCortex);
        if (fallback) currentRegisteredShortcut = DEFAULT_SETTINGS.globalShortcut;
      }
      return { success: false, error: `Could not register '${cleaned}'. It may be reserved by macOS.` };
    }
  } catch (err) {
    return { success: false, error: err.message };
  }
}

// ─── macOS System Tray & Menu Bar Implementation (P0) ─────────────────────────
function getTrayIconPath(status = "ready") {
  const assetsDir = path.join(__dirname, "assets");
  switch (status) {
    case "listening":
      return path.join(assetsDir, "trayListening.png");
    case "processing":
      return path.join(assetsDir, "trayProcessing.png");
    case "speaking":
      return path.join(assetsDir, "traySpeaking.png");
    case "error":
      return path.join(assetsDir, "trayError.png");
    case "ready":
    default:
      return path.join(assetsDir, "trayTemplate.png");
  }
}

function updateTrayMenu() {
  if (!tray) return;

  const statusLabels = {
    ready: "● Cortex: Ready",
    listening: "◉ Cortex: Listening…",
    processing: "◌ Cortex: Thinking…",
    speaking: "🔊 Cortex: Speaking…",
    error: "⚠ Cortex: Attention Needed",
  };

  const statusText = statusLabels[trayCurrentStatus] || "● Cortex: Ready";

  const contextMenu = Menu.buildFromTemplate([
    {
      label: statusText,
      enabled: false,
    },
    { type: "separator" },
    {
      label: "Open Cortex",
      click: () => {
        if (!mainWin) createMainWindow();
        if (isFloatingMode) {
          ipcMain.emit("set-window-mode", null, "standard");
        }
        mainWin.show();
        mainWin.focus();
      },
    },
    {
      label: "Open Floating Assistant",
      click: () => {
        if (!mainWin) createMainWindow();
        if (!isFloatingMode) {
          ipcMain.emit("set-window-mode", null, "floating");
        }
        mainWin.show();
        mainWin.focus();
        mainWin.webContents.send("focus-composer");
      },
    },
    {
      label: "Start Voice Interaction",
      accelerator: companionSettings.globalShortcut || "Command+Shift+A",
      click: () => {
        summonOrToggleCortex();
        if (mainWin) {
          mainWin.webContents.send("start-voice-interaction");
        }
      },
    },
    {
      label: companionSettings.wakeWordEnabled ? "Pause Wake-Word Detection" : "Enable Wake-Word ('Hey Cortex')",
      type: "checkbox",
      checked: Boolean(companionSettings.wakeWordEnabled),
      click: () => {
        companionSettings.wakeWordEnabled = !companionSettings.wakeWordEnabled;
        saveSettings(companionSettings);
        if (mainWin) {
          mainWin.webContents.send("companion-settings-changed", companionSettings);
        }
        updateTrayMenu();
      },
    },
    {
      label: "New Conversation",
      accelerator: "CmdOrCtrl+N",
      click: () => {
        if (!mainWin) createMainWindow();
        mainWin.show();
        mainWin.focus();
        mainWin.webContents.send("new-thread");
      },
    },
    {
      label: "Preferences & Settings…",
      accelerator: "CmdOrCtrl+,",
      click: () => {
        if (!mainWin) createMainWindow();
        mainWin.show();
        mainWin.focus();
        mainWin.webContents.send("open-settings");
      },
    },
    { type: "separator" },
    {
      label: "Quit Cortex",
      accelerator: "CmdOrCtrl+Q",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.setToolTip(`Cortex Desktop Companion — ${statusText.replace(/^[●◉◌🔊⚠]\s*/, "")}`);
}

function createTray() {
  if (tray) return;

  const iconPath = getTrayIconPath(trayCurrentStatus);
  let trayImage;
  try {
    trayImage = nativeImage.createFromPath(iconPath);
    if (trayCurrentStatus === "ready") {
      trayImage.setTemplateImage(true);
    }
  } catch (err) {
    console.warn("[electron] Error loading tray icon:", err);
  }

  tray = new Tray(trayImage || nativeImage.createEmpty());
  tray.setIgnoreDoubleClickEvents(true);

  tray.on("click", () => {
    summonOrToggleCortex();
  });

  updateTrayMenu();
}

function setTrayStatus(status) {
  trayCurrentStatus = status;
  if (!tray) return;

  const iconPath = getTrayIconPath(status);
  try {
    const img = nativeImage.createFromPath(iconPath);
    if (status === "ready") img.setTemplateImage(true);
    tray.setImage(img);
  } catch {}
  updateTrayMenu();
}

// ─── App Lifecycle & Startup ──────────────────────────────────────────────────
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

  createTray();
  createMainWindow();
  createHudWindow();

  // Register Global Summon Shortcut (Default: Command+Shift+A)
  registerGlobalSummonShortcut(companionSettings.globalShortcut);

  // Command palette toggle (CommandOrControl+K)
  try {
    globalShortcut.register("CommandOrControl+K", () => {
      if (mainWin) {
        if (!mainWin.isVisible()) mainWin.show();
        mainWin.focus();
        mainWin.webContents.send("toggle-palette");
      }
    });
  } catch {}
});

// ─── Floating Assistant Mode Controls (P0 & P3) ───────────────────────────────
ipcMain.on("set-window-mode", (event, mode) => {
  if (!mainWin) return;
  const display = getActiveDisplay();

  if (mode === "floating") {
    if (!isFloatingMode && mainWin) {
      companionSettings.standardBounds = mainWin.getBounds();
    }
    isFloatingMode = true;

    const floatWidth = Math.max(380, companionSettings.floatingBounds?.width || 440);
    const floatHeight = Math.min(
      display.workArea.height - 48,
      companionSettings.floatingBounds?.height || 720
    );

    // Compute active display coordinates
    const targetX = companionSettings.floatingBounds?.x !== undefined
      ? companionSettings.floatingBounds.x
      : computeFloatingPosition(display, floatWidth, floatHeight).x;
    const targetY = companionSettings.floatingBounds?.y !== undefined
      ? companionSettings.floatingBounds.y
      : computeFloatingPosition(display, floatWidth, floatHeight).y;

    mainWin.setAlwaysOnTop(Boolean(companionSettings.alwaysOnTop), "floating");
    mainWin.setBounds({
      x: targetX,
      y: targetY,
      width: floatWidth,
      height: floatHeight,
    });
    mainWin.webContents.send("window-mode-changed", "floating");
    saveSettings(companionSettings);
  } else {
    isFloatingMode = false;
    mainWin.setAlwaysOnTop(false);
    const std = companionSettings.standardBounds || { width: 1120, height: 760 };
    if (std.width && std.height && std.x !== undefined && std.y !== undefined) {
      mainWin.setBounds(std);
    } else {
      mainWin.setSize(1120, 760);
      mainWin.center();
    }
    mainWin.webContents.send("window-mode-changed", "standard");
    saveSettings(companionSettings);
  }
});

ipcMain.handle("get-window-mode", () => {
  return isFloatingMode ? "floating" : "standard";
});

ipcMain.on("hide-window", () => {
  if (mainWin && mainWin.isVisible()) {
    mainWin.hide();
  }
});

ipcMain.on("focus-window", () => {
  if (mainWin) {
    if (!mainWin.isVisible()) mainWin.show();
    mainWin.focus();
  }
});

// ─── Companion Settings IPC (P1) ──────────────────────────────────────────────
ipcMain.handle("get-companion-settings", () => {
  return companionSettings;
});

ipcMain.handle("update-companion-settings", (event, partial) => {
  if (!partial || typeof partial !== "object") return companionSettings;

  // Whitelist configuration keys to prevent arbitrary injection
  const allowedKeys = [
    "globalShortcut",
    "alwaysOnTop",
    "closeOnBlur",
    "escapeHides",
    "rememberBounds",
    "startMinimized",
    "launchAtLogin",
    "wakeWordEnabled",
    "wakeWordSensitivity",
    "audioInputDevice",
    "audioOutputDevice",
  ];

  for (const k of allowedKeys) {
    if (k in partial) {
      companionSettings[k] = partial[k];
    }
  }

  // Handle launch at login
  if ("launchAtLogin" in partial && process.platform === "darwin") {
    try {
      app.setLoginItemSettings({
        openAtLogin: Boolean(companionSettings.launchAtLogin),
        openAsHidden: Boolean(companionSettings.startMinimized),
      });
    } catch (err) {
      console.warn("[electron] Error updating login item settings:", err);
    }
  }

  // Handle always on top dynamic change
  if ("alwaysOnTop" in partial && mainWin && isFloatingMode) {
    mainWin.setAlwaysOnTop(Boolean(companionSettings.alwaysOnTop), "floating");
  }

  saveSettings(companionSettings);
  updateTrayMenu();
  return companionSettings;
});

ipcMain.handle("set-global-shortcut", (event, newShortcut) => {
  const result = registerGlobalSummonShortcut(newShortcut);
  if (result.success) {
    companionSettings.globalShortcut = result.shortcut;
    saveSettings(companionSettings);
    updateTrayMenu();
  }
  return result;
});

ipcMain.on("set-tray-status", (event, status) => {
  if (typeof status === "string") {
    setTrayStatus(status);
  }
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

// Clean shutdown
app.on("before-quit", () => {
  isQuitting = true;
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  if (isQuitting || process.platform !== "darwin") {
    globalShortcut.unregisterAll();
    app.quit();
  }
});

app.on("activate", () => {
  if (mainWin) {
    mainWin.show();
    mainWin.focus();
  } else {
    createMainWindow();
    createHudWindow();
  }
});
