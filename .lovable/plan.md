
# Print Blockage Stopper — React Dashboard

## Summary
Build a modern React dashboard for the Print Blockage Stopper Docker app with a **switchable light/dark theme** (dark by default). The app manages printers, schedules, print status, and history, connecting to the existing Python API on port 8631.

## Visual Style
- **Dark mode** (default): Deep background (#0a0a0f), neon cyan (#00d4ff) accents, green/red status colors, glowing card borders
- **Light mode**: Clean white/gray background, same accent palette adapted for light, subtle shadows instead of glows
- **Theme toggle** in the top bar (sun/moon icon), persisted to localStorage
- Monospace fonts for data, clean sans-serif for UI

## Pages & Features

### 1. Dashboard (Home)
- Global status bar: total printers, active/paused/error counts, "Print All" button
- Printer cards grid: name, IP, status glow, next-print countdown timer, pause/resume toggle, "Print Now" button, ink levels bar, test image thumbnail

### 2. Add / Edit Printer Dialogs
- Manual entry (IP, name, connection type, port)
- Network discovery via `/api/discover`
- Schedule picker (daily, every 2/3 days, weekly, custom cron)
- Test connection with live probe results
- Test image selector

### 3. History & Logs
- Print history table with filters (printer, result, date)
- 30-day chart (Recharts)
- CSV export
- Terminal-style log viewer (auto-scrolling)

### 4. Settings
- Webhook URL, email (SMTP), Home Assistant integration config
- Test notification buttons

### 5. Demo Mode
- Toggle between mock data and live backend connection
- Works without a running Docker container

## Tech Stack
- React 18, TypeScript, Vite, Tailwind CSS v3
- TanStack Query (polling every 30s), React Router, Recharts, Lucide React, Sonner
- Theme context with CSS variables for light/dark switching

## Implementation Steps
1. Scaffold app: index.html, main.tsx, App.tsx, Tailwind config with dark/light theme tokens
2. Theme provider with toggle, persisted to localStorage
3. Types & API service layer mapping to all Python endpoints
4. Layout shell: sidebar nav + top bar with theme toggle and global stats
5. Dashboard page: printer cards grid with status polling, countdown timers, actions
6. Add/Edit printer dialogs with discovery, schedule picker, test connection
7. History page: table + chart + CSV export
8. Settings page: webhook, email, HA config forms
9. Log viewer: terminal-style scrolling display
10. Polish: loading skeletons, error states, responsive layout, animations
