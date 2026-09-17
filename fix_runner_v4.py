import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

NL = chr(10)
EM = chr(8212)

start = src.find("def _execute_run_visible(step, log):")
end = src.find(NL + "def _execute_run(step", start)
if start < 0 or end < 0:
    print("FAIL: bounds for _execute_run_visible")
    raise SystemExit(1)

new_visible = '''def _execute_run_visible(step, log):
    """Visible PowerShell window, isolation-safe."""
    preview_raw = step.cmd.replace(chr(10), " ").replace(chr(34), "'")[:60]
    preview = preview_raw.replace("'", "''")
    token = uuid.uuid4().hex[:8]
    tmpdir = Path(tempfile.gettempdir())
    userscript = tmpdir / ("psedit_user_" + token + ".ps1")
    wrapper = tmpdir / ("psedit_visible_" + token + ".ps1")
    logfile = tmpdir / ("psedit_visible_" + token + ".log")

    userscript.write_text(step.cmd, encoding="utf-8")

    logfile_str = str(logfile).replace("'", "''")
    user_str = str(userscript).replace("'", "''")
    wl = [
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
    wrapper.write_text(chr(10).join(wl), encoding="utf-8")

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
            _hard = _eta_val * 2
            while proc.poll() is None:
                _el = time.time() - started
                if _el > _hard:
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

src = src[:start] + new_visible + src[end:]
print("OK   _execute_run_visible rewritten")

anchor = "def _execute_run_visible(step, log):"
helper = '''def _notify_via_powershell(title, msg):
    """Windows toast without any third-party Python package."""
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

if anchor in src:
    src = src.replace(anchor, helper, 1)
    print("OK   _notify_via_powershell helper added")
else:
    print("MISS helper anchor")
    raise SystemExit(1)

idx = src.find('        elif step.kind == "notify":')
if idx < 0:
    print("MISS notify (index)")
    raise SystemExit(1)
nxt = src.find('        elif step.kind == "update":', idx)
if nxt < 0:
    nxt = src.find('        elif step.kind == "run":', idx)
if nxt < 0:
    print("MISS next branch after notify")
    raise SystemExit(1)

new_notify_block = (
    '        elif step.kind == "notify":' + NL
    + '            if dry_run:' + NL
    + '                log.append(("info", "   [dry-run] would notify: " + step.cmd[:60]))' + NL
    + '                log.append(("blank", "")); continue' + NL
    + '            _title = "PSEdit ' + EM + ' AI needs input"' + NL
    + '            _body = step.cmd' + NL
    + '            _ok, _m = send_toast(_title, _body, parent_widget=None, on_click=None)' + NL
    + '            if not _ok:' + NL
    + '                _ok, _m = _notify_via_powershell(_title, _body)' + NL
    + '            log.append(("ok" if _ok else "warn",' + NL
    + '                        "   notification via " + _m + ("" if _ok else " (all methods failed)")))' + NL
    + '            log.append(("blank", ""))' + NL
    + NL
)

src = src[:idx] + new_notify_block + src[nxt:]
print("OK   notify branch rewritten")

idx2 = src.find('                if rc == 0:' + NL + '                    written.append(step.path)')
if idx2 < 0:
    print("MISS office rollback anchor")
    raise SystemExit(1)

old_block = (
    '                if rc == 0:' + NL
    + '                    written.append(step.path)' + NL
    + '                    git_paths.add(str(p.resolve()))' + NL
    + '                    log.append(("ok", f"   ' + chr(92) + 'u2713 {step.office_kind} edits applied and validated"))' + NL
    + '                else:'
)
new_block = (
    '                written.append(step.path)' + NL
    + '                git_paths.add(str(p.resolve()))' + NL
    + '                if rc == 0:' + NL
    + '                    log.append(("ok", f"   ' + chr(92) + 'u2713 {step.office_kind} edits applied and validated"))' + NL
    + '                else:'
)

if old_block in src:
    src = src.replace(old_block, new_block, 1)
    print("OK   office rollback tracks written")
else:
    print("MISS office rollback text")
    raise SystemExit(1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("fix_runner_v4 done")