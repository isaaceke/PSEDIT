# PSEdit V12

V12 replaces the previous browser/native transaction pipeline with one persistent native connection and one PseDIT runtime window.

## Architecture

- Browser extension owns browser routing only.
- `request_id` identifies one operation end-to-end.
- The originating `tabId`, `documentId`, and `frameId` are captured when the PSL is detected.
- PseDIT owns execution and multiple background `Worker` jobs.
- One PseDIT native window displays the process monitor.
- `PSCOPY`, `PSEDIT`, `PSFIND`, `PSTREE`, `PSRUN`, and `PSRUNADMIN` return through the same result channel.
- `chrome.storage.local` is no longer used as the transport/state machine.

Chrome documents `connectNative()` as the extension-to-native-app persistent port API, and `tabs.sendMessage()` supports `documentId`/`frameId` targeting for a specific document/frame. See the official Chrome documentation.

## Windows one-run build/install

From this folder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-v12.ps1 -ExtensionId ccfjhlgddhaagncmcoefnfmlmnkokeih
```

The script builds `dist\PseDIT.exe`, embeds `PSEDIT.ico`, copies the icon beside the executable, writes the native-host manifest, and registers the native host for Chrome, Brave, and Edge.

PyInstaller must be run on Windows to produce the Windows executable. The build uses a console-enabled executable with the console hidden early so Native Messaging still has stdio while the user does not get a visible console window.
