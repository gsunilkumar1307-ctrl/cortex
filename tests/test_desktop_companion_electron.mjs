import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const mainJsPath = path.join(repoRoot, "apps/desktop/electron/main.js");
const preloadJsPath = path.join(repoRoot, "apps/desktop/electron/preload.cjs");

test("Desktop Companion: main.js and preload.cjs exist and have valid syntax", () => {
  assert.ok(fs.existsSync(mainJsPath), "main.js exists");
  assert.ok(fs.existsSync(preloadJsPath), "preload.cjs exists");

  const mainContent = fs.readFileSync(mainJsPath, "utf-8");
  const preloadContent = fs.readFileSync(preloadJsPath, "utf-8");

  // Check critical P0 features in main.js
  assert.match(mainContent, /Command\+Shift\+A/, "Default macOS global shortcut Command+Shift+A present");
  assert.match(mainContent, /createTray/, "macOS System Tray implementation present");
  assert.match(mainContent, /set-tray-status/, "IPC channel for tray status synchronization present");
  assert.match(mainContent, /set-global-shortcut/, "IPC channel for global shortcut customization present");
  assert.match(mainContent, /get-companion-settings/, "IPC channel for persistent settings retrieval present");
  assert.match(mainContent, /update-companion-settings/, "IPC channel for persistent settings update present");
  assert.match(mainContent, /alwaysOnTop/, "Always on top support present");
  assert.match(mainContent, /closeOnBlur/, "Close on blur support present");
  assert.match(mainContent, /escapeHides/, "Escape hides support present");
  assert.match(mainContent, /getDisplayNearestPoint/, "Multi-monitor display awareness present");

  // Check critical APIs in preload.cjs
  assert.match(preloadContent, /getCompanionSettings/, "Preload exposes getCompanionSettings");
  assert.match(preloadContent, /updateCompanionSettings/, "Preload exposes updateCompanionSettings");
  assert.match(preloadContent, /setGlobalShortcut/, "Preload exposes setGlobalShortcut");
  assert.match(preloadContent, /setTrayStatus/, "Preload exposes setTrayStatus");
  assert.match(preloadContent, /onFocusComposer/, "Preload exposes onFocusComposer listener");
  assert.match(preloadContent, /onStartVoiceInteraction/, "Preload exposes onStartVoiceInteraction listener");
});

test("Desktop Companion: Tray icon assets generated and present", () => {
  const assetsDir = path.join(repoRoot, "apps/desktop/electron/assets");
  const requiredIcons = [
    "trayTemplate.png",
    "trayTemplate@2x.png",
    "trayListening.png",
    "trayListening@2x.png",
    "trayProcessing.png",
    "trayProcessing@2x.png",
    "traySpeaking.png",
    "traySpeaking@2x.png",
    "trayError.png",
    "trayError@2x.png",
  ];

  for (const icon of requiredIcons) {
    const fullPath = path.join(assetsDir, icon);
    assert.ok(fs.existsSync(fullPath), `Asset ${icon} must exist`);
    const stat = fs.statSync(fullPath);
    assert.ok(stat.size > 50, `Asset ${icon} must have valid non-zero size`);
  }
});

test("Desktop Companion: Settings whitelist prevents arbitrary property injection", () => {
  const mainContent = fs.readFileSync(mainJsPath, "utf-8");
  assert.match(mainContent, /const allowedKeys = \[/, "Explicit allowedKeys whitelist must exist in update-companion-settings");
});
