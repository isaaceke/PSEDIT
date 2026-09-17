import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

def sub(old, new, label):
    global src
    if old in src:
        src = src.replace(old, new, 1)
        print("OK  " + label)
        return True
    print("MISS " + label)
    raise SystemExit(1)

# Data structures
sub(
    '''@dataclass
class Script:
    blocks:      list = field(default_factory=list)
    copy_blocks: list = field(default_factory=list)
    find_blocks: list = field(default_factory=list)
    run_blocks:  list = field(default_factory=list)
    tree_blocks: list = field(default_factory=list)''',
    '''@dataclass
class NotifyBlock:
    message: str
    line: int = 0

@dataclass
class UpdateBlock:
    line: int = 0

@dataclass
class Script:
    blocks:      list = field(default_factory=list)
    copy_blocks: list = field(default_factory=list)
    find_blocks: list = field(default_factory=list)
    run_blocks:  list = field(default_factory=list)
    tree_blocks: list = field(default_factory=list)
    notify_blocks: list = field(default_factory=list)
    update_blocks: list = field(default_factory=list)''',
    "NotifyBlock + UpdateBlock"
)

# Parser state
sub(
    '''    blocks, copies, finds, runs, trees = [], [], [], [], []''',
    '''    blocks, copies, finds, runs, trees = [], [], [], [], []
    notifies, updates = [], []''',
    "parser state"
)

# Parser close
sub(
    '''    def close_all():
        close_find(); close_edit(); close_run(); close_tree()''',
    '''    def close_notify():
        nonlocal notify_buf, notify_line
        if notify_line:
            msg = chr(10).join(notify_buf).strip()
            if msg:
                notifies.append(NotifyBlock(msg, notify_line))
        notify_buf, notify_line = [], 0

    def close_all():
        close_find(); close_edit(); close_run(); close_tree(); close_notify()''',
    "close_notify"
)

sub(
    '''    tree_root, tree_line, tree_buf = None, 0, []''',
    '''    tree_root, tree_line, tree_buf = None, 0, []
    notify_buf, notify_line = [], 0''',
    "notify state"
)

# Dispatch
sub(
    '''            elif s == MARK_PSTREE:  mode = "tree_path"
            continue''',
    '''            elif s == MARK_PSTREE:  mode = "tree_path"
            elif s == MARK_PSNOTIFY: notify_line = ln; notify_buf = []; mode = "notify_text"
            elif s == MARK_PSUPDATE: updates.append(UpdateBlock(ln)); mode = "idle"
            continue''',
    "dispatch"
)

# Body accumulation
sub(
    '''        if mode == "run":       run_buf.append(line); continue
        if mode == "tree_body": tree_buf.append(line); continue''',
    '''        if mode == "run":        run_buf.append(line); continue
        if mode == "tree_body":  tree_buf.append(line); continue
        if mode == "notify_text": notify_buf.append(line); continue''',
    "notify body"
)

sub(
    '''    close_all()
    return Script(blocks, copies, finds, runs, trees, cb, keep, gp, stop, session_id), errs''',
    '''    close_all()
    return Script(blocks, copies, finds, runs, trees, cb, keep, gp, stop, session_id,
                  notifies=notifies, update_blocks=updates), errs''',
    "return with notifies"
)

sub(
    '''    cb, keep, gp, stop, session_id = False, 3, False, True, ""''',
    '''    cb, keep, gp, stop, session_id = True, 3, False, True, ""''',
    "create_bak default true"
)

# build_plan: add steps
sub(
    '''    for t in script.tree_blocks: actions.append((t.line, "tree", t))
    actions.sort(key=lambda x: x[0])''',
    '''    for t in script.tree_blocks: actions.append((t.line, "tree", t))
    for n in script.notify_blocks: actions.append((n.line, "notify", n))
    for u in script.update_blocks: actions.append((u.line, "update", u))
    actions.sort(key=lambda x: x[0])''',
    "plan actions"
)

sub(
    '''        elif kind == "tree":
            t = obj
            p, err = safe_path(t.root)
            step = PlanStep(kind="tree", line=t.line,
                            tree_root=str(p or t.root), tree_entries=t.entries)''',
    '''        elif kind == "notify":
            n = obj
            step = PlanStep(kind="notify", line=n.line, label="NOTIFY  " + n.message[:50])
            step.cmd = n.message
            steps.append(step)

        elif kind == "update":
            u = obj
            step = PlanStep(kind="update", line=u.line, label="UPDATE  rebuild and relaunch")
            steps.append(step)

        elif kind == "tree":
            t = obj
            p, err = safe_path(t.root)
            step = PlanStep(kind="tree", line=t.line,
                            tree_root=str(p or t.root), tree_entries=t.entries)''',
    "plan notify/update"
)

# execute_plan: add branches
sub(
    '''        elif step.kind == "run":
            if dry_run:
                log.append(("info", "   [dry-run] would execute"))
                log.append(("blank", "")); continue''',
    '''        elif step.kind == "notify":
            if dry_run:
                log.append(("info", "   [dry-run] would notify: " + step.cmd[:60]))
                log.append(("blank", "")); continue
            _ok, _m = send_toast("PSEdit \u2014 AI needs input", step.cmd,
                                 parent_widget=None, on_click=None)
            log.append(("ok" if _ok else "warn",
                        f"   notification via {_m}" + ("" if _ok else " (no tray available)")))
            log.append(("blank", ""))

        elif step.kind == "update":
            if dry_run:
                log.append(("info", "   [dry-run] would rebuild"))
                log.append(("blank", "")); continue
            _bat = Path(tempfile.gettempdir()) / ("psedit_update_" + uuid.uuid4().hex[:8] + ".bat")
            _root = str(SELF_PATH.parent)
            if not Path(_root + chr(92) + "PseDIT_v15.spec").exists():
                _root = r"C:\\Users\\HP\\Downloads\\PSEDIT"
            _lines = [
                "@echo off",
                "timeout /t 2 /nobreak > nul",
                "taskkill /F /IM brave.exe 2>nul",
                "taskkill /F /IM PseDIT.exe 2>nul",
                "taskkill /F /IM py.exe 2>nul",
                "timeout /t 2 /nobreak > nul",
                "cd /d " + _root,
                "if not exist dist\\.bak mkdir dist\\.bak",
                "copy /Y dist\\PseDIT.exe dist\\.bak\\PseDIT_prev.exe >nul",
                "C:\\Python314\\python.exe -m PyInstaller --clean PseDIT_v15.spec",
                "start \"\" \"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe\"",
                "exit /b 0",
            ]
            _bat.write_bytes((chr(13) + chr(10)).join(_lines).encode("utf-8") + bytes([13, 10]))
            _creation = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
            try:
                subprocess.Popen(["cmd", "/c", str(_bat)], creationflags=_creation,
                                 close_fds=True)
                log.append(("ok", "   update batch launched, this window will close"))
            except Exception as _e:
                log.append(("err", "   update launch failed: " + str(_e)))
                fatal = True
                if script.stop_on_err: break
            log.append(("blank", ""))

        elif step.kind == "run":
            if dry_run:
                log.append(("info", "   [dry-run] would execute"))
                log.append(("blank", "")); continue''',
    "execute notify/update"
)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("patch_g done")