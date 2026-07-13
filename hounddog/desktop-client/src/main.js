const { app, BrowserWindow, Tray, Menu, Notification, nativeImage, dialog } = require("electron");
const path = require("path");
const Store = require("electron-store");

const store = new Store({
  defaults: {
    serverUrl: "https://quarry.moravian.edu",
    showOnStartup: true,
    soundEnabled: true,
  },
});

let tray = null;
let settingsWindow = null;
let eventSource = null;
let reconnectTimer = null;
const RECONNECT_DELAY = 5000;

function createTray() {
  const iconPath = path.join(__dirname, "..", "assets", "tray-icon.png");
  let icon;
  try {
    icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  } catch {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  tray.setToolTip("Quarry Alerts — Connected");

  const contextMenu = Menu.buildFromTemplate([
    { label: "Quarry Desktop Alerts", enabled: false },
    { type: "separator" },
    {
      label: "Connection Status",
      sublabel: "Connecting...",
      id: "status",
      enabled: false,
    },
    { type: "separator" },
    {
      label: "Settings...",
      click: () => openSettings(),
    },
    {
      label: "Test Notification",
      click: () => showNotification("Test Alert", "This is a test notification from Quarry Desktop Alerts.", "general"),
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        disconnect();
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on("double-click", () => openSettings());
}

function updateTrayStatus(status) {
  if (!tray) return;
  tray.setToolTip(`Quarry Alerts — ${status}`);
}

function showNotification(title, body, category) {
  if (!Notification.isSupported()) return;

  const urgency = category === "emergency" ? "critical" : "normal";

  const notification = new Notification({
    title,
    body,
    urgency,
    silent: !store.get("soundEnabled"),
    timeoutType: category === "emergency" ? "never" : "default",
  });

  notification.show();
}

function connect() {
  const serverUrl = store.get("serverUrl");
  const sseUrl = `${serverUrl}/api/alerts/desktop/sse`;

  disconnect();

  console.log(`Connecting to ${sseUrl}...`);
  updateTrayStatus("Connecting...");

  const EventSource = require("eventsource");

  eventSource = new EventSource(sseUrl);

  eventSource.addEventListener("connected", () => {
    console.log("SSE connected");
    updateTrayStatus("Connected");
  });

  eventSource.addEventListener("alert", (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log("Alert received:", data.subject);
      showNotification(
        `${data.category?.toUpperCase() ?? "ALERT"}: ${data.subject}`,
        data.body_text || data.subject,
        data.category,
      );
    } catch (err) {
      console.error("Failed to parse alert event:", err);
    }
  });

  eventSource.addEventListener("clear", (event) => {
    try {
      const data = JSON.parse(event.data);
      showNotification("Alert Cleared", `Alert ${data.id} has been cleared.`, "general");
    } catch (err) {
      console.error("Failed to parse clear event:", err);
    }
  });

  eventSource.onerror = (err) => {
    console.error("SSE error:", err);
    updateTrayStatus("Disconnected");
    eventSource.close();
    eventSource = null;

    reconnectTimer = setTimeout(() => {
      console.log("Attempting reconnect...");
      connect();
    }, RECONNECT_DELAY);
  };
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function openSettings() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 420,
    height: 340,
    resizable: false,
    title: "Quarry Alerts Settings",
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });

  settingsWindow.loadFile(path.join(__dirname, "settings.html"));
  settingsWindow.setMenuBarVisibility(false);

  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });
}

app.whenReady().then(() => {
  if (process.platform === "darwin") {
    app.dock.hide();
  }

  createTray();
  connect();
});

app.on("window-all-closed", (e) => {
  e.preventDefault();
});

app.on("before-quit", () => {
  disconnect();
});
