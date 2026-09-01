# AI Usage Pulse

UsagePulse is a small Windows desktop widget that combines:

- New API balance and rolling 24-hour usage.
- ChatGPT/Codex 5-hour and weekly plan limits.
- A system-tray menu, automatic refresh, and low-balance alerts.

## Project layout

```text
ai-usage-pulse/
├── main.py                       # Desktop application
├── chatgpt_bridge.py             # Loopback-only extension receiver
├── chatgpt_usage_extension/      # Unpacked Chrome extension
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Packaging dependencies
├── run_monitor.cmd               # Console launcher
├── run_monitor.vbs               # Silent launcher
├── install_autostart.ps1         # Windows startup shortcut
└── build.ps1                     # Optional single-file build
```

Local state is intentionally excluded from Git:

- `config.json` contains non-secret preferences and the New API user ID.
- The New API Access Token is stored in Windows Credential Manager.
- `.venv`, caches, debug captures, and build output are ignored.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run_monitor.cmd
```

Use `run_monitor.vbs` when you want to launch without a console window.

## New API connection

Open `New API` in the widget and enter:

- Platform URL: `https://ai-platform.5xgames.com`
- Dashboard Access Token: create it under `Profile → Access Token`
- User ID: the numeric ID shown on the profile page

The widget refreshes New API automatically every 30 minutes by default. The `Refresh` button performs an immediate New API update and also requests a ChatGPT/Codex Usage re-sync.

## ChatGPT/Codex sync

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose `Load unpacked` and select `chatgpt_usage_extension`.
4. After source changes, use the extension page's `Reload` button once.
5. Click `ChatGPT` in UsagePulse to open the Codex Analytics Usage page, or disable **Open the fixed ChatGPT/Codex Usage page** in settings if you do not want UsagePulse to navigate Chrome.

The extension reads only visible plan-limit text. It never reads cookies, local storage, passwords, prompts, or conversations, and it sends values only to `127.0.0.1:8765`.

The extension syncs after page changes and checks again every 30 seconds. Clicking `Refresh` in UsagePulse asks any open ChatGPT/Codex Usage page to re-read and re-sync within about two seconds; the widget then displays **ChatGPT/Codex Usage updated.** when it receives the new values. If Chrome or the Usage page is closed, UsagePulse keeps the most recently received values but cannot obtain newer ChatGPT limits until a Usage page is opened again.

## Start with Windows

Run once:

```powershell
.\install_autostart.ps1
```

## Optional executable build

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\build.ps1
```

The executable is generated at `dist\UsagePulse.exe` and is not committed to Git.
