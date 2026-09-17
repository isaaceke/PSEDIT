import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

def sub(old, new, label, required=True):
    global src
    if old in src:
        src = src.replace(old, new, 1)
        print("OK  " + label)
        return True
    print("MISS " + label)
    if required:
        raise SystemExit(1)
    return False

# 1. RunBlock gets eta field
sub(
    '''@dataclass
class RunBlock:
    cmd: str
    admin: bool = False
    mode: str = "concurrent"
    line: int = 0
    visible: bool = False''',
    '''@dataclass
class RunBlock:
    cmd: str
    admin: bool = False
    mode: str = "concurrent"
    line: int = 0
    visible: bool = False
    eta: int = 0''',
    "RunBlock.eta"
)

# 2. PlanStep gets eta
sub(
    '''    visible: bool = False
    office_kind: str = ""''',
    '''    visible: bool = False
    eta: int = 0
    office_kind: str = ""''',
    "PlanStep.eta"
)

# 3. Parser: recognize eta:N in run options
sub(
    '''            run_buf, run_line, run_is_admin, run_mode, run_visible = [], 0, False, "concurrent", False
    pending_copy_range = None''',
    '''            run_buf, run_line, run_is_admin, run_mode, run_visible = [], 0, False, "concurrent", False
    pending_copy_range = None''',
    "noop parser anchor",
    required=False
)

sub(
    '''            run_visible = True
            for o in opts:
                if o in ("ordered", "concurrent"):
                    run_mode = "concurrent"
                elif o in ("parallel", "simultaneous"):
                    run_mode = "simultaneous"
                elif o == "visible":
                    run_visible = True
                elif o == "hidden":
                    run_visible = False
            continue''',
    '''            run_visible = True
            for o in opts:
                if o in ("ordered", "concurrent"):
                    run_mode = "concurrent"
                elif o in ("parallel", "simultaneous"):
                    run_mode = "simultaneous"
                elif o == "visible":
                    run_visible = True
                elif o == "hidden":
                    run_visible = False
            _eta = 0
            for o in opts:
                if o.startswith("eta:"):
                    try:
                        _eta = int(o.split(":", 1)[1].strip())
                    except ValueError:
                        _eta = 0
            run_eta = _eta
            continue''',
    "parse eta:N"
)

sub(
    '''    run_buf, run_line, run_is_admin, run_mode, run_visible = [], 0, False, "concurrent", False
    pending_copy_range = None''',
    '''    run_buf, run_line, run_is_admin, run_mode, run_visible, run_eta = [], 0, False, "concurrent", False, 0
    pending_copy_range = None''',
    "run_eta init"
)

sub(
    '''    def close_run():
        nonlocal run_buf, run_is_admin, run_mode, run_visible
        if run_buf:
            cmd = "\\n".join(run_buf).rstrip("\\n")
            if cmd: runs.append(RunBlock(cmd, run_is_admin, run_mode, run_line, run_visible))
        run_buf, run_is_admin, run_mode, run_visible = [], False, "concurrent", False''',
    '''    def close_run():
        nonlocal run_buf, run_is_admin, run_mode, run_visible, run_eta
        if run_buf:
            cmd = "\\n".join(run_buf).rstrip("\\n")
            if cmd: runs.append(RunBlock(cmd, run_is_admin, run_mode, run_line, run_visible, run_eta))
        run_buf, run_is_admin, run_mode, run_visible, run_eta = [], False, "concurrent", False, 0''',
    "close_run eta"
)

# 4. build_plan passes eta
sub(
    '''            step = PlanStep(kind="run", line=r.line, cmd=r.cmd, admin=r.admin, mode=r.mode,
                            session_id=script.session_id,
                            visible=getattr(r, "visible", False),
                            label=f"{tag} [{r.mode}]{vis_tag}  {first}")''',
    '''            step = PlanStep(kind="run", line=r.line, cmd=r.cmd, admin=r.admin, mode=r.mode,
                            session_id=script.session_id,
                            visible=getattr(r, "visible", False),
                            eta=getattr(r, "eta", 0),
                            label=f"{tag} [{r.mode}]{vis_tag}  {first}")''',
    "plan passes eta"
)

# 5. Office branch: capture output into run_results
sub(
    '''                if rc == 0:
                    written.append(step.path)
                    git_paths.add(str(p.resolve()))
                    log.append(("ok", f"   \\u2713 {step.office_kind} edits applied and validated"))
                else:
                    log.append(("err", f"   \\u2717 {step.office_kind} edit failed (rc={rc})"))
                    fatal = True
                    if script.stop_on_err: break''',
    '''                _office_out = []
                try:
                    if _logfile.exists():
                        _raw2 = _logfile.read_text(encoding="utf-8", errors="replace")
                        _office_out = [ln.rstrip(chr(13)) for ln in _raw2.split(chr(10)) if ln.strip()]
                except Exception:
                    pass
                _office_result = {
                    "id": uuid.uuid4().hex,
                    "job_id": getattr(step, "job_id", "") or ("job_" + uuid.uuid4().hex),
                    "request_id": getattr(step, "request_id", ""),
                    "session_id": getattr(step, "session_id", ""),
                    "status": "success" if rc == 0 else "failed",
                    "mode": getattr(step, "mode", "concurrent"),
                    "admin": False,
                    "command": step.office_kind + " edit: " + step.path,
                    "cwd": str(Path.cwd()),
                    "exit_code": rc,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time())),
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time())),
                    "duration_seconds": 0,
                    "output": chr(10).join(_office_out) if _office_out else "(no output)",
                    "via_worker": False,
                }
                run_results.append(_office_result)
                if rc == 0:
                    written.append(step.path)
                    git_paths.add(str(p.resolve()))
                    log.append(("ok", f"   \\u2713 {step.office_kind} edits applied and validated"))
                else:
                    log.append(("err", f"   \\u2717 {step.office_kind} edit failed (rc={rc})"))
                    if _office_out:
                        for _o in _office_out[-10:]:
                            log.append(("err", "     " + _o))
                    fatal = True
                    if script.stop_on_err: break''',
    "office output captured"
)

# 6. _execute_run_visible: respect eta for early warnings
sub(
    '''    pspath.write_text(chr(10).join(ps_lines), encoding="utf-8")
    started = time.time()
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
    log.append(("info", "   launching PowerShell: " + pspath.name))
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(pspath)],
            creationflags=creation,
        )
        proc.wait()
        rc = proc.returncode''',
    '''    pspath.write_text(chr(10).join(ps_lines), encoding="utf-8")
    started = time.time()
    creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
    log.append(("info", "   launching PowerShell: " + pspath.name))
    _eta_val = getattr(step, "eta", 0) or 0
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(pspath)],
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
                    log.append(("warn", f"   exceeded eta {_eta_val}s x2, killed at {int(_el)}s"))
                    break
                if not _warned and _el > _eta_val:
                    log.append(("warn", f"   running past eta {_eta_val}s, still working ({int(_el)}s)"))
                    _warned = True
                time.sleep(0.5)
        proc.wait()
        rc = proc.returncode''',
    "eta monitor"
)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("patch_f done")