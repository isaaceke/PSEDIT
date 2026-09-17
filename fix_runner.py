import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

NL = chr(10)

# ── Fix 2, 7, 8, 9: rewrite _execute_run_visible ─────────────────────────
start = src.find("def _execute_run_visible(step, log):")
end = src.find(NL + "def _execute_run(step", start)
if start < 0 or end < 0:
    print("FAIL: could not locate _execute_run_visible bounds")
    raise SystemExit(1)

new_fn = '''def _execute_run_visible(step, log):
    """Visible PowerShell window.

    Isolation strategy:
      * user's command goes into its own .ps1 file
      * that file is invoked via powershell.exe -File, so `exit N` inside
        it terminates only the child, not the visible wrapper
      * wrapper sets $ErrorActionPreference = 'Stop', runs try/catch to
        catch non-terminating errors that $LASTEXITCODE cannot
      * stdout/stderr are transcribed to a log file and echoed to the
        visible window; log is read back with utf-8-sig to strip BOM
    """
    preview_raw = step.cmd.replace(chr(10), " ").replace(chr(34), "'")[:60]
    preview = preview_raw.replace("'", "''")
    token = uuid.uuid4().hex[:8]
    tmpdir = Path(tempfile.gettempdir())
    userscript = tmpdir / ("psedit_user_" + token + ".ps1")
    wrapper = tmpdir / ("psedit_visible_" + token + ".ps1")
    logfile = tmpdir / ("psedit_visible_" + token + ".log")

    # user script: the raw command, verbatim, no surrounding braces
    userscript.write_text(step.cmd, encoding="utf-8")

    logfile_str = str(logfile).replace("'", "''")
    user_str = str(userscript).replace("'", "''")
    wrapper_lines = [
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
        "$Host.UI.RawUI.WindowTitle = 'PSEdit - " + preview + "'",
        "$logfile = '" + logfile_str + "'",
        "$userScript = '" + user_str + "'",
        "$rc = 1",
        "try {",
        "    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $userScript 2>&1 |",
        "        ForEach-Object {",
        "            $line = $_.ToString()",
        "            Write-Host $line",
        "            Add-Content -Path $logfile -Value $line -Encoding UTF8",
        "        }",
        "    $rc = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 0 }",
        "} catch {",
        "    $msg = $_.Exception.Message",
        "    Write-Host $msg",
        "    Add-Content -Path $logfile -Value $msg -Encoding UTF8",
        "    $rc = 1",
        "}",
        "Write-Host ''",
        "Write-Host ('-- PSEdit exit: ' + $rc + ' --')",
        "if ($rc -ne 0) {",
        "    Write-Host ''",
        "    Write-Host 'Press any key to close...'",
        "    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')",
        "}",
        "exit $rc",
    ]
    wrapper.write_text(chr(10).join(wrapper_lines), encoding="utf-8")

    started = time.time()
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
    log.append(("info", "   launching PowerShell: " + wrapper.name))
    _eta_val = getattr(step, "eta", 0) or 0
    rc = -1
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
            creationflags=creation,
        )
        if _eta_val > 0:
            _warned = False
            _hard_limit = _eta_val * 2
            while proc.poll() is None:
                _el = time.time() - started
                if _el > _hard_limit:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    log.append(("warn", "   exceeded eta " + str(_eta_val) + "s x2, killed at " + str(int(_el)) + "s"))
                    break
                if not _warned and _el > _eta_val:
                    log.append(("warn", "   running past eta " + str(_eta_val) + "s, still working (" + str(int(_el)) + "s)"))
                    _warned = True
                time.sleep(0.5)
        proc.wait()
        rc = proc.returncode
    except Exception as e:
        log.append(("err", "   visible launch failed: " + str(e)))
        rc = -1

    output_lines = []
    try:
        if logfile.exists():
            raw = logfile.read_text(encoding="utf-8-sig", errors="replace")
            output_lines = [ln.rstrip(chr(13)) for ln in raw.split(chr(10)) if ln.strip()]
        else:
            output_lines = ["(no output captured)"]
    except Exception as e:
        output_lines = ["(failed to read log: " + str(e) + ")"]

    for _f in (userscript, wrapper, logfile):
        try:
            _f.unlink(missing_ok=True)
        except Exception:
            pass

    finished = time.time()
    log.append(("ok" if rc == 0 else "warn",
                "   " + ("OK" if rc == 0 else "FAIL") + " exit " + str(rc) + " (visible PowerShell)"))
    result = {
        "id": uuid.uuid4().hex,
        "job_id": getattr(step, "job_id", "") or ("job_" + uuid.uuid4().hex),
        "request_id": getattr(step, "request_id", ""),
        "session_id": getattr(step, "session_id", ""),
        "status": "success" if rc == 0 else "failed",
        "mode": getattr(step, "mode", "concurrent"),
        "visible": True,
        "admin": False,
        "command": step.cmd,
        "cwd": str(Path.cwd()),
        "exit_code": rc,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished)),
        "duration_seconds": round(finished - started, 3),
        "output": chr(10).join(output_lines),
        "via_worker": False,
    }
    return rc == 0, result
'''

src = src[:start] + new_fn + src[end:]
print("OK   _execute_run_visible rewritten (bugs 2, 7, 8, 9)")

# ── Fix 4: psnotify uses powershell toast via subprocess ────────────────
old_notify = '''        elif step.kind == "notify":
            if dry_run:
                log.append(("info", "   [dry-run] would notify: " + step.cmd[:60]))
                log.append(("blank", "")); continue
            _ok, _m = send_toast("PSEdit \\u2014 AI needs input", step.cmd,
                                 parent_widget=None, on_click=None)
            log.append(("ok" if _ok else "warn",
                        f"   notification via {_m}" + ("" if _ok else " (no tray available)")))
            log.append(("blank", ""))'''

new_notify = '''        elif step.kind == "notify":
            if dry_run:
                log.append(("info", "   [dry-run] would notify: " + step.cmd[:60]))
                log.append(("blank", "")); continue
            _title = "PSEdit \\u2014 AI needs input"
            _body = step.cmd
            _ok, _m = send_toast(_title, _body, parent_widget=None, on_click=None)
            if not _ok:
                _ok, _m = _notify_via_powershell(_title, _body)
            log.append(("ok" if _ok else "warn",
                        "   notification via " + _m + ("" if _ok else " (all methods failed)")))
            log.append(("blank", ""))'''

if old_notify in src:
    src = src.replace(old_notify, new_notify, 1)
    print("OK   psnotify uses powershell fallback")
else:
    # Try with actual em-dash
    old_notify2 = old_notify.replace("\\\\u2014", "\\u2014").replace("\\\\", "\\")
    if old_notify2 in src:
        src = src.replace(old_notify2, new_notify.replace("\\\\u2014", "\\u2014").replace("\\\\", "\\"), 1)
        print("OK   psnotify uses powershell fallback (alt)")
    else:
        print("MISS notify anchor")
        raise SystemExit(1)

# Add _notify_via_powershell helper before _execute_run_visible
anchor_helper = "def _execute_run_visible(step, log):"
new_helper = '''def _notify_via_powershell(title, msg):
    """Fire a Windows toast without any third-party Python library."""
    def xesc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;")
                 .replace("'", "&apos;"))
    tx = xesc(title)
    mx = xesc(msg)
    ps = (
        "$ErrorActionPreference='Stop';"
        "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime];"
        "[void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime];"
        "[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime];"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$x.LoadXml('<toast><visual><binding template=\\"ToastGeneric\\"><text>" + tx + "</text><text>" + mx + "</text></binding></visual></toast>');"
        "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('" + APP_ID + "').Show($t)"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=20, creationflags=flags)
        if r.returncode == 0:
            return True, "powershell-toast"
        return False, "powershell-toast-exit-" + str(r.returncode)
    except Exception as e:
        return False, "powershell-toast-error"


def _execute_run_visible(step, log):'''

if anchor_helper in src:
    src = src.replace(anchor_helper, new_helper, 1)
    print("OK   _notify_via_powershell helper added")
else:
    print("MISS helper anchor")
    raise SystemExit(1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("fix_runner done")