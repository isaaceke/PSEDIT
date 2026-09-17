import io, shutil, re
from pathlib import Path

ROOT = Path(r"C:\Users\HP\Downloads\PSEDIT")
V14 = ROOT / "PseDIT_v14.py"
V15 = ROOT / "PseDIT_v15.py"
S14 = ROOT / "PseDIT_v14.spec"
S15 = ROOT / "PseDIT_v15.spec"

shutil.copy2(str(V14), str(V15))
shutil.copy2(str(S14), str(S15))

with io.open(str(V15), "r", encoding="utf-8") as f:
    src = f.read()

def sub(old, new, label, required=True):
    global src
    if old in src:
        src = src.replace(old, new, 1)
        print("OK  " + label)
        return True
    print("MISS " + label)
    if required:
        print("  anchor:", repr(old[:180]))
        raise SystemExit(1)
    return False

# 1. Version
sub('APP_VERSION = "14.1.0"', 'APP_VERSION = "15.0.0"', "version 15.0.0")

# 2. Add new markers
sub(
    'MARK_XLSX     = "psxlsx::"\nMARK_DOCX     = "psdocx::"',
    'MARK_XLSX     = "psxlsx::"\nMARK_DOCX     = "psdocx::"\nMARK_PSNOTIFY = "psnotify::"\nMARK_PSUPDATE = "psupdate::"',
    "add markers"
)

sub(
    '                MARK_XLSX, MARK_DOCX}\n_PATH_MARKERS',
    '                MARK_XLSX, MARK_DOCX, MARK_PSNOTIFY, MARK_PSUPDATE}\n_PATH_MARKERS',
    "register in _ALL_MARKERS"
)

# 3. Replace _execute_run_visible with PowerShell version
start = src.find("def _execute_run_visible(step, log):")
if start < 0:
    print("MISS _execute_run_visible signature")
    raise SystemExit(1)
end = src.find("\ndef ", start + 1)
if end < 0:
    print("MISS next def after _execute_run_visible")
    raise SystemExit(1)

new_fn = '''def _execute_run_visible(step, log):
    """Visible PowerShell window. Multi-line commands run as one script."""
    preview_raw = step.cmd.replace(chr(10), " ").replace(chr(34), "'")[:70]
    preview = preview_raw.replace("'", "''")
    token = uuid.uuid4().hex[:8]
    tmpdir = Path(tempfile.gettempdir())
    pspath = tmpdir / ("psedit_visible_" + token + ".ps1")
    logfile = tmpdir / ("psedit_visible_" + token + ".log")
    logfile_str = str(logfile).replace("'", "''")
    ps_lines = [
        "$ErrorActionPreference = 'Continue'",
        "$Host.UI.RawUI.WindowTitle = 'PSEdit - " + preview + "'",
        "$logfile = '" + logfile_str + "'",
        "& {",
        step.cmd,
        "} 2>&1 | ForEach-Object {",
        "    Write-Host $_",
        "    $_ | Out-File -FilePath $logfile -Append -Encoding utf8",
        "}",
        "$rc = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 0 }",
        "Write-Host ''",
        "Write-Host ('-- PSEdit exit: ' + $rc + ' --')",
        "if ($rc -ne 0) {",
        "    Write-Host ''",
        "    Write-Host 'Press any key to close...'",
        "    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')",
        "}",
        "exit $rc",
    ]
    pspath.write_text(chr(10).join(ps_lines), encoding="utf-8")
    started = time.time()
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
    log.append(("info", "   launching PowerShell: " + pspath.name))
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(pspath)],
            creationflags=creation,
        )
        proc.wait()
        rc = proc.returncode
    except Exception as e:
        log.append(("err", "   visible launch failed: " + str(e)))
        rc = -1

    output_lines = []
    try:
        if logfile.exists():
            raw = logfile.read_text(encoding="utf-8", errors="replace")
            output_lines = [ln.rstrip(chr(13)) for ln in raw.split(chr(10)) if ln.strip()]
        else:
            output_lines = ["(no output captured)"]
    except Exception as e:
        output_lines = ["(failed to read log: " + str(e) + ")"]

    try:
        pspath.unlink(missing_ok=True)
        logfile.unlink(missing_ok=True)
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
print("OK  PowerShell runner replaces .bat/cmd")

# 4. Window geometry memory
sub(
    '''    def closeEvent(self, e):
        for job in list(self._jobs.values()):
            if job.worker is not None and job.worker.isRunning():
                job.worker.cancel()
        self._native.stop()
        super().closeEvent(e)


class Main(QMainWindow):''',
    '''    def closeEvent(self, e):
        try:
            _cfg = Path(os.environ.get("APPDATA", "")) / "PseDIT"
            _cfg.mkdir(parents=True, exist_ok=True)
            _geo = self.geometry()
            (_cfg / "window.json").write_text(
                json.dumps({
                    "x": _geo.x(), "y": _geo.y(),
                    "w": _geo.width(), "h": _geo.height(),
                    "maximized": bool(self.windowState() & Qt.WindowState.WindowMaximized)
                    if _QT6 else bool(self.windowState() & Qt.WindowMaximized)
                }), encoding="utf-8")
        except Exception:
            pass
        try:
            self._watchdog.stop()
        except Exception:
            pass
        for job in list(self._jobs.values()):
            if job.worker is not None and job.worker.isRunning():
                job.worker.cancel()
        self._native.stop()
        super().closeEvent(e)


class Main(QMainWindow):''',
    "geometry save on close", required=False
)

sub(
    '''        self._native = NativeBridge()
        self._jobs = {}
        self._queue = []
        self._active = set()
        self._max_parallel = 4''',
    '''        self._native = NativeBridge()
        self._jobs = {}
        self._queue = []
        self._active = set()
        self._max_parallel = 4

        try:
            _cfg = Path(os.environ.get("APPDATA", "")) / "PseDIT"
            _gf = _cfg / "window.json"
            if _gf.exists():
                _g = json.loads(_gf.read_text(encoding="utf-8"))
                self.setGeometry(int(_g["x"]), int(_g["y"]), int(_g["w"]), int(_g["h"]))
                if _g.get("maximized"):
                    if _QT6:
                        self.setWindowState(Qt.WindowState.WindowMaximized)
                    else:
                        self.setWindowState(Qt.WindowMaximized)
        except Exception:
            pass''',
    "geometry restore on init", required=False
)

with io.open(str(V15), "w", encoding="utf-8", newline="") as f:
    f.write(src)

# 5. Update spec
with io.open(str(S15), "r", encoding="utf-8") as f:
    spec = f.read()
spec = spec.replace("PseDIT_v14.py", "PseDIT_v15.py")
with io.open(str(S15), "w", encoding="utf-8", newline="") as f:
    f.write(spec)

print("V15 SOURCE READY")
print("Spec: " + str(S15))