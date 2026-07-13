# Quarry Desktop Alert Client

Electron-based system tray application that receives real-time campus alerts via SSE (Server-Sent Events) and displays native OS notifications.

## Features

- System tray icon with connection status
- Real-time alert notifications via SSE
- Emergency alerts show as critical/persistent notifications
- Alert cleared notifications
- Configurable server URL
- Auto-reconnect on connection loss
- Runs silently in the system tray (no dock icon on macOS)

## Development

```bash
npm install
npm start
```

## Building

```bash
# Windows (for SCCM deployment)
npm run build:win

# macOS
npm run build:mac
```

## Deployment

The Windows build produces an NSIS installer suitable for SCCM deployment:
- One-click install, per-machine
- Output in `dist/` directory

## Configuration

Settings are stored in electron-store (persistent across restarts):
- **Server URL**: The Quarry server base URL (default: `https://quarry.moravian.edu`)
- **Sound**: Enable/disable notification sounds
- **Startup**: Auto-start with system

## Architecture

The client connects to `/api/alerts/desktop/sse` on the Quarry server. Events:
- `connected` — Initial connection confirmation
- `alert` — New alert dispatched (shows notification)
- `clear` — Alert cleared (shows dismissal notification)
- Keepalive pings every 30 seconds maintain the connection
