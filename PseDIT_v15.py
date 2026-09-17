#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PSEdit — paste a PSL script, it edits (or creates) your files.
"""

from __future__ import annotations

import codecs
import ctypes
import difflib
import html
import json
import os
import re
import struct
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
APP_ID = "PSEdit.App.1"
APP_VERSION = "15.0.0"
NATIVE_EXTENSION_ID = "ccfjhlgddhaagncmcoefnfmlmnkokeih"

def _set_app_id():
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

_set_app_id()

# --- Qt shim ----------------------------------------------------------------
try:
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize, QRect, QPoint, QObject
    from PyQt6.QtGui import (
        QColor, QFont, QIcon, QKeySequence, QSyntaxHighlighter,
        QTextCharFormat, QTextCursor, QShortcut, QPixmap,
    )
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
        QHBoxLayout, QLabel, QLayout, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QScrollArea, QSplitter, QSystemTrayIcon, QTextEdit, QToolButton,
        QVBoxLayout, QWidget,
    )
    _QT6 = True
    _END       = QTextCursor.MoveOperation.End
    _MB_YES    = QMessageBox.StandardButton.Yes
    _MB_NO     = QMessageBox.StandardButton.No
    _DB_ACTION = QDialogButtonBox.ButtonRole.ActionRole
    _DB_CLOSE  = QDialogButtonBox.StandardButton.Close
    _KEEP_ON_TOP = Qt.WindowType.WindowStaysOnTopHint
    _KEY_ESC   = Qt.Key.Key_Escape
    _WIN_MIN   = Qt.WindowState.WindowMinimized
    _WIN_ACT   = Qt.WindowState.WindowActive
    _TRAY_INFO = QSystemTrayIcon.MessageIcon.Information
    _CURSOR_PT = Qt.CursorShape.PointingHandCursor
    _ORIENT_V  = Qt.Orientation.Vertical
except ImportError:
    from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize, QRect, QPoint, QObject
    from PyQt5.QtGui import (
        QColor, QFont, QIcon, QKeySequence, QSyntaxHighlighter,
        QTextCharFormat, QTextCursor, QPixmap,
    )
    from PyQt5.QtWidgets import (
        QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
        QHBoxLayout, QLabel, QLayout, QMainWindow, QMessageBox, QPlainTextEdit,
        QPushButton, QScrollArea, QSplitter, QSystemTrayIcon, QTextEdit, QToolButton,
        QVBoxLayout, QWidget,
    )
    _QT6 = False
    _END       = QTextCursor.End
    _MB_YES    = QMessageBox.Yes
    _MB_NO     = QMessageBox.No
    _DB_ACTION = QDialogButtonBox.ActionRole
    _DB_CLOSE  = QDialogButtonBox.Close
    _KEEP_ON_TOP = Qt.WindowStaysOnTopHint
    _KEY_ESC   = Qt.Key.Key_Escape
    _WIN_MIN   = Qt.WindowMinimized
    _WIN_ACT   = Qt.WindowActive
    _TRAY_INFO = QSystemTrayIcon.Information
    _CURSOR_PT = Qt.PointingHandCursor
    _ORIENT_V  = Qt.Vertical

APP_NAME    = "PSEdit"

# ── Safety limits (invisible caps, no UX cost) ───────────────────────────────
MAX_FILE_BYTES  = 10 * 1024 * 1024
MAX_REGEX_BYTES = 2 * 1024 * 1024
MAX_RUN_SECONDS = 600
HOME_DIR        = Path.home().resolve()

# ──────────────────────────────────────────────────────────────────────────────
PROMPT_TEXT = r'''You are a file-editing assistant. I use a personal DSL called PSEdit (PSL).

IMPORTANT RESPONSE CONTRACT:
- When the request requires PSEdit, return ONE complete PSL payload in ONE code/text block.
- Do not leak PSL markers while thinking or discussing what you might do.
- Do not split one operation across multiple code blocks.
- Do not put PSL markers in ordinary explanatory prose.
- The PSL payload should use the envelope below for browser automation.
- The envelope begins at column 0 with __PSEDIT_BEGIN__ session=<opaque-token>.
- The PSL payload must end with exactly one line: __finish__
- Put __finish__ only after ALL PSL code is complete.
- Do not write anything after __finish__.
- If the request does NOT require PSEdit, answer normally and do not emit PSL markers.

RUN MODES:
- psrun{ordered}:: = ordered execution. Commands run in script order.
- psrun{parallel}:: = parallel execution for independent commands.
- psrunadmin{ordered}:: and psrunadmin{parallel}:: are the elevated equivalents.
- Compatibility aliases: concurrent → ordered; simultaneous → parallel.
- Plain psrun:: / psrunadmin:: means ordered for backward compatibility.

RESULT HANDSHAKE:
- Preserve the session token from __PSEDIT_BEGIN__ in every PSRESULT.
- Every completed run produces machine-readable PSRESULT text.
- PSRESULT is designed for ANY consuming AI, not just the one that issued
  the PSL. It carries status, per-step results, exit codes, and a summary
  line that can be quoted verbatim.
- A simultaneous batch produces one aggregate PSRESULT batch only after ALL jobs finish.
- The browser extension must wait for __finish__ before looking for PSL to copy.
- Never copy partial text, hidden/thinking text, quoted PSL, or an unfinished answer.

AUTOMATION ENVELOPE:
__PSEDIT_BEGIN__ session=<opaque-token>
<all PSL blocks>
__finish__

BLOCKS (each starts at column 0 with its marker):

# 1) Edit a file — replace ALL occurrences of <old> with <new>:
psedit::
"<absolute path>"
psfrom::
<old text>
psto::
<new text>

# 2) Regex edit (Python re, MULTILINE | DOTALL):
psregex::
"<absolute path>"
psfrom::
<regex pattern>
psto::
<replacement — \1, \g<name> for groups>

# 3) Create a NEW file — leave psfrom:: EMPTY:
psedit::
"<absolute path>"
psfrom::
psto::
<full file content>

# 4) Copy file(s) to clipboard (no edits):
pscopy::
"<absolute path>"

# 5) Copy only PART of a file:
pscopy{351-600}::
pscopy{351}::
pscopy{351-}::
pscopy{-600}::
pscopy{start_marker:::end_marker}::
pscopy{start_marker:::*}::
pscopy{*:::end_marker}::

# 6) Search a file (no edits, shows line numbers + context):
psfind::
"<absolute path>"
psfrom::
<substring>

# 7) Run a shell command — VISIBLE console by default.
#     Opens a real PowerShell window, runs the command live, closes
#     automatically on success, pauses on failure so you can read
#     the output. The same output is returned in PSRESULT.output.
#     To run hidden instead, add the option 'hidden' inside the
#     curly braces alongside the mode (e.g. simultaneous,hidden).
psrun{concurrent}::
<command line — may span multiple lines>

# 7b) Run with a VISIBLE console window:
#     Opens a real terminal, runs live, auto-closes on exit 0,
#     pauses on failure so the user can read the output.
psrun{visible}::
<command line>

# 7c) Combine mode and visibility: psrun{concurrent,visible}::
#     or psrun{simultaneous,visible}::

# 8) Run several independent commands at once:
psrun{simultaneous}::
<command line — may span multiple lines>

# 9) Run elevated sequentially:
psrunadmin{concurrent}::
<command line>

# 10) Run elevated in parallel:
psrunadmin{simultaneous}::
<command line>

# 11) Scaffold a project tree — dirs end with "/", files may have # comments:
pstree::
"<absolute root path>"
src/
    main.py                 # Entry point
    utils/
        helpers.py          # Helper functions
tests/
    test_main.py            # Tests

RULES:
- Multiple psfrom::/psto:: pairs may be stacked inside one edit block.
- Blocks run top-to-bottom in the order written.
- Path on the line after the marker, wrapped in double quotes.
- Windows backslashes are literal: C:\Users\PC\f.yaml  (NOT C:\\Users\\PC)
- Exact match (case & whitespace sensitive) unless psregex:: is used.
- Trailing blank lines in psfrom/psto bodies are ignored.
- Empty psto:: body deletes the matched text.
- Parent directories auto-created.
- Keep all related PSL in one payload and finish it with __finish__.

VERSIONING CONVENTION:
- Every edit to an existing file (text, docx, xlsx) automatically saves a
  versioned copy to .bak/ next to the original, named <name>_v<N><ext>.
- Set create.bak {false} to opt out; create.bak {N} controls keep count.
- Exes and binaries are not backed up; only source and document files.

OPTIONS (anywhere, one per line):
  create.bak    {true|false|N}   # .bak/ folder next to each edited file;
                                 # duplicate is renamed to <name>_v<N><ext>;
                                 # keep N most recent (default 3); default ON.
                                 # Setting create.bak {false} disables versioning.
  Git push      {true|false}     # stage + commit + push ONLY files PSEdit touched
  stop.on.error {true|false}     # default true: abort + rollback on any miss
                                 # (stop.onerror also accepted — same option)

MY REQUEST:
<describe the change you want here>

__finish__
'''


# --- Parser -----------------------------------------------------------------
MARK_EDIT     = "psedit::"
MARK_FROM     = "psfrom::"
MARK_TO       = "psto::"
MARK_COPY     = "pscopy::"
MARK_FIND     = "psfind::"
MARK_REGEX    = "psregex::"
MARK_RUN      = "psrun::"
MARK_RUNADMIN = "psrunadmin::"
_RUN_MARK_RE = re.compile(r"^(?P<admin>psrunadmin|psrun)(?:\{(?P<opts>[^}]*)\})?::$", re.IGNORECASE)
MARK_PSTREE   = "pstree::"
MARK_XLSX     = "psxlsx::"
MARK_DOCX     = "psdocx::"
MARK_PSNOTIFY = "psnotify::"
MARK_PSUPDATE = "psupdate::"

_ALL_MARKERS = {MARK_EDIT, MARK_FROM, MARK_TO, MARK_COPY, MARK_FIND,
                MARK_REGEX, MARK_RUN, MARK_RUNADMIN, MARK_PSTREE,
                MARK_XLSX, MARK_DOCX, MARK_PSNOTIFY, MARK_PSUPDATE}
_PATH_MARKERS = {MARK_EDIT, MARK_REGEX, MARK_COPY, MARK_FIND, MARK_PSTREE,
                 MARK_XLSX, MARK_DOCX}

OPTION_RE = re.compile(
    r"^(?P<name>create\.bak|git\s*push|stop\.on\.error)"
    r"\s*\{\s*(?P<val>true|false|\d+)\s*\}\s*$",
    re.IGNORECASE,
)
_SESSION_BEGIN_RE = re.compile(r"^__PSEDIT_BEGIN__\s+session=(?P<id>[A-Za-z0-9._:-]+)\s*$", re.IGNORECASE)

_INLINE_COPY_RE = re.compile(r"^pscopy\{.*\}$", re.IGNORECASE)

_PSL_PREFIXES = (
    "psedit::", "pscopy::", "pscopy{", "psregex::",
    "psfind::", "psrun::", "psrun{", "psrunadmin::",
    "psrunadmin{", "pstree::",
)
FINISH_MARK = "__finish__"
PSRESULT_START = "PSRESULT::1"
PSRESULT_END = "__PSRESULT_END__"
PSRESULTS_START = "PSRESULTS::1"
PSRESULTS_END = "__PSRESULTS_END__"
PSPLAN_PROTOCOL = "PSPLAN/1"
MAX_NATIVE_MESSAGE_BYTES = 1024 * 1024

def sha256_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()

def authoritative_file_record(p):
    data = p.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise IOError(f"file too large: {len(data)} bytes > {MAX_FILE_BYTES}")
    bom = data.startswith(codecs.BOM_UTF8)
    raw = data[len(codecs.BOM_UTF8):] if bom else data
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8-sig" if bom else "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replacement"
    return {
        "path": str(p),
        "sha256": sha256_bytes(data),
        "size": len(data),
        "encoding": encoding,
        "content": text.replace("\r\n", "\n"),
    }

def native_file_reads(script):
    records = []
    for c in script.copy_blocks:
        p, err = safe_path(c.path)
        if err or p is None:
            records.append({"path": c.path, "error": err or "invalid path"})
            continue
        try:
            rec = authoritative_file_record(p)
            if c.range_spec:
                sliced, range_err = extract_range(rec["content"], c.range_spec)
                if range_err:
                    rec["error"] = range_err
                    rec.pop("content", None)
                else:
                    rec["content"] = sliced
                    rec["range"] = c.range_spec
            records.append(rec)
        except Exception as e:
            records.append({"path": str(p), "error": str(e)})
    return records

def typed_operations(script):
    ops = []
    actions = []
    actions.extend((b.line, b) for b in script.blocks)
    actions.extend((c.line, c) for c in script.copy_blocks)
    actions.extend((f.line, f) for f in script.find_blocks)
    actions.extend((r.line, r) for r in script.run_blocks)
    actions.extend((t.line, t) for t in script.tree_blocks)
    for line, obj in sorted(actions, key=lambda x: x[0]):
        if isinstance(obj, Block):
            p, _ = safe_path(obj.path)
            if obj.kind == "xlsx":
                ops.append({"type": "patch_xlsx", "path": str(p or obj.path), "line": line,
                            "operations": [{"cell": r.old, "value": r.new} for r in obj.reps]})
            elif obj.kind == "docx":
                ops.append({"type": "patch_docx", "path": str(p or obj.path), "line": line,
                            "operations": [{"find": r.old, "replace": r.new} for r in obj.reps]})
            else:
                ops.append({"type": "patch_file", "path": str(p or obj.path), "line": line, "regex": bool(obj.regex),
                            "operations": [{"old": r.old, "new": r.new} for r in obj.reps]})
        elif isinstance(obj, CopyBlock):
            p, _ = safe_path(obj.path)
            ops.append({"type": "read_file", "path": str(p or obj.path), "line": line, "range": obj.range_spec or None})
        elif isinstance(obj, FindBlock):
            p, _ = safe_path(obj.path)
            ops.append({"type": "search_files", "path": str(p or obj.path), "line": line, "query": obj.query})
        elif isinstance(obj, RunBlock):
            ops.append({"type": "run", "command": obj.cmd, "admin": bool(obj.admin), "mode": obj.mode, "line": line})
        elif isinstance(obj, TreeBlock):
            p, _ = safe_path(obj.root)
            ops.append({"type": "create_tree", "root": str(p or obj.root), "line": line,
                        "entries": [{"path": e.rel_path, "directory": e.is_dir, "content": e.content} for e in obj.entries]})
    return ops

def make_psplan(script, request_id="", session_id=""):
    ops = typed_operations(script)
    resources = []
    seen = set()
    for op in ops:
        target = op.get("path") or op.get("root")
        if target and target not in seen:
            seen.add(target)
            resources.append({"key": target, "mode": "write" if op["type"] in ("patch_file", "create_tree") else "read"})
    return {
        "protocol": PSPLAN_PROTOCOL,
        "request_id": request_id or uuid.uuid4().hex,
        "session_id": session_id or script.session_id or uuid.uuid4().hex,
        "operations": ops,
        "ordering": "source_order",
        "parallel_groups": [],
        "barriers": [],
        "resource_locks": resources,
        "policy": {"default": "allow", "admin": "approval_required", "git_push": "approval_required" if script.git_push else "not_requested"},
    }

def extract_psl_payload(text):
    """Return PSL only when the entire payload is complete and explicitly terminated."""
    if not text:
        return None
    stripped = text.strip()
    finish_re = re.compile(r"(?m)^" + re.escape(FINISH_MARK) + r"\s*$")
    if not finish_re.search(stripped):
        return None

    # Preferred form: the clipboard content itself is the complete PSL payload.
    low = stripped.lower()
    if low.startswith(_PSL_PREFIXES) and stripped.endswith(FINISH_MARK):
        return stripped
    if _SESSION_BEGIN_RE.match(stripped.splitlines()[0]) and stripped.endswith(FINISH_MARK):
        return stripped

    # Backward-compatible fenced form, but ONLY when the fence contains the
    # complete payload and there is no surrounding prose.
    m = re.fullmatch(r"\s*```(?:psl|psedit)?\s*\n(.*?)\n?```\s*", text,
                     re.DOTALL | re.IGNORECASE)
    if m:
        body = m.group(1).strip()
        if body.lower().startswith(_PSL_PREFIXES) and body.endswith(FINISH_MARK):
            return body
    return None

# --- Data types -------------------------------------------------------------
@dataclass
class Rep:
    old: str
    new: str

@dataclass
class Block:
    path: str
    reps: list = field(default_factory=list)
    line: int = 0
    regex: bool = False
    kind: str = "text"

@dataclass
class CopyBlock:
    path: str
    line: int = 0
    range_spec: str = ""

@dataclass
class FindBlock:
    path: str
    query: str
    line: int = 0

@dataclass
class RunBlock:
    cmd: str
    admin: bool = False
    mode: str = "concurrent"
    line: int = 0
    visible: bool = False
    eta: int = 0

def make_psresult(result):
    payload = dict(result)
    return PSRESULT_START + "\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n" + PSRESULT_END

def make_psresults(results, batch_id=None):
    payload = {
        "batch_id": batch_id or uuid.uuid4().hex,
        "count": len(results),
        "results": results,
    }
    return PSRESULTS_START + "\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n" + PSRESULTS_END

@dataclass
class TreeEntry:
    rel_path: str
    is_dir: bool
    content: str

@dataclass
class TreeBlock:
    root: str
    entries: list
    line: int = 0

@dataclass
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
    update_blocks: list = field(default_factory=list)
    create_bak:  bool = True
    bak_keep:    int  = 3
    git_push:    bool = False
    stop_on_err: bool = True
    session_id: str = ""
    request_id: str = ""

    def has_admin(self):   return any(r.admin for r in self.run_blocks)
    def has_shell(self):   return bool(self.run_blocks)
    def has_simultaneous(self): return any(r.mode == "simultaneous" for r in self.run_blocks)

@dataclass
class PlanStep:
    kind: str
    line: int
    label: str = ""
    path: str = ""
    new_content: str = ""
    old_content: str = ""
    bom: bool = False
    crlf: bool = False
    is_new_file: bool = False
    matches: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    copy_payload: str = ""
    copy_bytes: int = 0
    copy_lines: int = 0
    find_hits: list = field(default_factory=list)
    find_source: list = field(default_factory=list)
    cmd: str = ""
    admin: bool = False
    mode: str = "concurrent"
    session_id: str = ""
    tree_root: str = ""
    tree_entries: list = field(default_factory=list)
    visible: bool = False
    eta: int = 0
    office_kind: str = ""
    office_edits: list = field(default_factory=list)
    office_validate: bool = True
    fatal: bool = False
    warnings: list = field(default_factory=list)
    expected_sha256: str = ""
    job_id: str = ""
    request_id: str = ""

# --- Parser -----------------------------------------------------------------
def _unq(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s

def _split_range_and_path(line: str):
    rng = ""
    body = line.strip()
    if body.endswith("}"):
        if body[:1] in ('"', "'"):
            q = body[0]
            close = body.find(q, 1)
            if close > 0:
                rest = body[close + 1:].strip()
                if rest.startswith("{") and rest.endswith("}"):
                    rng = rest[1:-1]
                    body = body[:close + 1]
    return body, rng

def _parse_tree_lines(lines, root: Path):
    entries = []
    stack = [(-1, root)]
    for raw in lines:
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(stripped)
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        name_part = stripped
        content   = ""
        if " #" in stripped:
            name_part, comment = stripped.rsplit(" #", 1)
            name_part = name_part.rstrip()
            content = "# " + comment.strip()
        if name_part.endswith("/"):
            name = name_part[:-1].strip(); is_dir = True
        else:
            name = name_part.strip(); is_dir = False
        if not name: continue
        rel = parent / name
        entries.append(TreeEntry(str(rel.relative_to(root)).replace("\\", "/"),
                                 is_dir, content))
        if is_dir:
            stack.append((indent, rel))
    return entries

def parse_script(text):
    errs = []
    blocks, copies, finds, runs, trees = [], [], [], [], []
    notifies, updates = [], []
    cb, keep, gp, stop, session_id = True, 3, False, True, ""
    path, path_line, reps = None, 0, []
    old, buf, mode = None, [], "idle"
    find_path, find_line = None, 0
    tree_root, tree_line, tree_buf = None, 0, []
    notify_buf, notify_line = [], 0
    is_regex_block = False
    edit_kind = "text"
    run_buf, run_line, run_is_admin, run_mode, run_visible, run_eta = [], 0, False, "concurrent", False, 0
    pending_copy_range = None

    def pair():
        nonlocal old, buf
        if old is None: buf = []; return
        reps.append(Rep(old, "\n".join(buf).rstrip("\n")))
        old, buf = None, []

    def close_find():
        nonlocal find_path, find_line, buf
        if find_path is not None:
            finds.append(FindBlock(find_path, "\n".join(buf).rstrip("\n"), find_line))
            find_path, find_line, buf = None, 0, []

    def close_edit():
        nonlocal path, reps, is_regex_block, edit_kind
        pair()
        if path is not None:
            blocks.append(Block(path, list(reps), path_line, is_regex_block, edit_kind))
        path, reps, is_regex_block, edit_kind = None, [], False, "text"

    def close_run():
        nonlocal run_buf, run_is_admin, run_mode, run_visible, run_eta
        if run_buf:
            cmd = "\n".join(run_buf).rstrip("\n")
            if cmd: runs.append(RunBlock(cmd, run_is_admin, run_mode, run_line, run_visible, run_eta))
        run_buf, run_is_admin, run_mode, run_visible, run_eta = [], False, "concurrent", False, 0

    def close_tree():
        nonlocal tree_root, tree_buf, tree_line
        if tree_root is not None:
            entries = _parse_tree_lines(tree_buf, Path(tree_root))
            trees.append(TreeBlock(tree_root, entries, tree_line))
        tree_root, tree_buf, tree_line = None, [], 0

    def close_notify():
        nonlocal notify_buf, notify_line
        if notify_line:
            msg = chr(10).join(notify_buf).strip()
            if msg:
                notifies.append(NotifyBlock(msg, notify_line))
        notify_buf, notify_line = [], 0

    def close_all():
        close_find(); close_edit(); close_run(); close_tree(); close_notify()

    for i, raw in enumerate(text.splitlines()):
        ln = i + 1
        line = raw.rstrip("\r")
        s = line.strip()

        begin_m = _SESSION_BEGIN_RE.match(s)
        if begin_m:
            session_id = begin_m.group("id")
            continue
        if s == FINISH_MARK:
            continue

        if s[:7].lower() == "pscopy{" and s.endswith("}"):
            close_all(); pending_copy_range = s[7:-1]; mode = "copy_path"; continue

        run_marker = _RUN_MARK_RE.match(s)
        if run_marker:
            close_all()
            mode = "run"
            run_line = ln
            run_is_admin = run_marker.group("admin").lower() == "psrunadmin"
            opts_str = (run_marker.group("opts") or "ordered").lower()
            opts = [o.strip() for o in opts_str.split(",") if o.strip()]
            run_mode = "concurrent"
            run_visible = True
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
            continue

        if s in _ALL_MARKERS:
            # psfrom:: and psto:: are structural markers inside the current edit.
            # They must NOT close the edit before their bodies are captured.
            if s == MARK_FROM:
                if mode == "path":
                    errs.append(f"line {ln}: psfrom:: before path")
                pair(); mode = "from"; buf = []
                continue
            if s == MARK_TO:
                if mode != "from":
                    errs.append(f"line {ln}: psto:: without psfrom::"); old = None
                else:
                    old = "\n".join(buf).rstrip("\n")
                buf = []; mode = "to"
                continue

            close_all()
            if s == MARK_EDIT:      mode = "path"; is_regex_block = False; edit_kind = "text"
            elif s == MARK_REGEX:   mode = "path"; is_regex_block = True; edit_kind = "text"
            elif s == MARK_XLSX:    mode = "path"; is_regex_block = False; edit_kind = "xlsx"
            elif s == MARK_DOCX:    mode = "path"; is_regex_block = False; edit_kind = "docx"
            elif s == MARK_COPY:    pending_copy_range = None; mode = "copy_path"
            elif s == MARK_FIND:    mode = "find_path"
            elif s == MARK_PSTREE:  mode = "tree_path"
            elif s == MARK_PSNOTIFY: notify_line = ln; notify_buf = []; mode = "notify_text"
            elif s == MARK_PSUPDATE: updates.append(UpdateBlock(ln)); mode = "idle"
            continue

        m = OPTION_RE.match(s)
        if m and mode in ("idle", "ready", "to", "path", "copy_path",
                          "find_path", "tree_path"):
            if mode == "to": pair()
            mode = "idle"
            name = m.group("name").lower().replace(" ", "")
            val  = m.group("val").lower()
            if name == "create.bak":
                if val in ("true", "false"): cb = (val == "true")
                else: cb = True; keep = max(1, min(50, int(val)))
            elif name == "gitpush":      gp = (val == "true")
            elif name == "stop.onerror" or name == "stop.on.error": stop = (val == "true")
            continue

        if mode == "run":        run_buf.append(line); continue
        if mode == "tree_body":  tree_buf.append(line); continue
        if mode == "notify_text": notify_buf.append(line); continue

        if mode == "idle":
            if not s or s.startswith("#"): continue
            errs.append(f"line {ln}: unexpected text: {s[:60]!r}"); continue
        if mode == "path":
            if not s or s.startswith("#"): continue
            path = _unq(s); path_line = ln; mode = "ready"; continue
        if mode == "copy_path":
            if not s or s.startswith("#"): continue
            path_str, rng_from_line = _split_range_and_path(s)
            rng = rng_from_line or (pending_copy_range or "")
            copies.append(CopyBlock(_unq(path_str), ln, rng))
            mode = "idle"; pending_copy_range = None
            continue
        if mode == "find_path":
            if not s or s.startswith("#"): continue
            find_path = _unq(s); find_line = ln; mode = "find_query"; continue
        if mode == "find_query":
            buf.append(line); continue
        if mode == "tree_path":
            if not s or s.startswith("#"): continue
            tree_root = _unq(s); tree_line = ln; mode = "tree_body"
            tree_buf = []
            continue
        if mode == "ready":
            if not s or s.startswith("#"): continue
            errs.append(f"line {ln}: expected psfrom::"); continue
        if mode in ("from", "to"):
            buf.append(line)

    if mode == "from":
        errs.append("end of script: psfrom:: never closed by psto::")
        old = None; buf = []
    close_all()
    return Script(blocks, copies, finds, runs, trees, cb, keep, gp, stop, session_id,
                  notifies=notifies, update_blocks=updates), errs

# --- Path safety (invisible) ------------------------------------------------
def safe_path(raw):
    """Expand ~ / env vars, resolve, reject symlinks. Returns (Path, err)."""
    if not raw:
        return None, "empty path"
    expanded = os.path.expanduser(os.path.expandvars(raw))
    if not os.path.isabs(expanded):
        return None, f"path must be absolute: {raw!r}"
    try:
        p = Path(expanded).resolve()
    except Exception as e:
        return None, f"cannot resolve: {e}"
    try:
        if p.exists() and p.is_symlink():
            return None, f"refusing symlink target: {p}"
        parent = p.parent
        while parent != parent.parent:
            if parent.is_symlink():
                return None, f"refusing path through symlink: {parent}"
            parent = parent.parent
    except OSError:
        pass
    return p, None

# --- File I/O ---------------------------------------------------------------
def read_text(p):
    try:
        size = p.stat().st_size
    except OSError as e:
        raise IOError(f"stat: {e}")
    if size > MAX_FILE_BYTES:
        raise IOError(f"file too large: {size} bytes > {MAX_FILE_BYTES}")
    try:
        data = p.read_bytes()
    except PermissionError:
        raise PermissionError(f"permission denied reading {p}")
    bom  = data.startswith(codecs.BOM_UTF8)
    if bom: data = data[len(codecs.BOM_UTF8):]
    crlf = b"\r\n" in data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n"), bom, crlf

def write_text(p, text, bom, crlf):
    out  = text.replace("\n", "\r\n") if crlf else text
    data = out.encode("utf-8")
    if bom: data = codecs.BOM_UTF8 + data
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".psedit_tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, str(p))
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

# --- Range extraction -------------------------------------------------------
def extract_range(text, spec):
    lines = text.split("\n")
    spec = (spec or "").strip()
    if not spec: return text, None
    if ":::" in spec:
        start_m, end_m = spec.split(":::", 1)
        start_m = start_m.strip(); end_m = end_m.strip()
        i_start = 0
        if start_m and start_m != "*":
            for k, ln in enumerate(lines):
                if start_m in ln: i_start = k; break
            else: return None, f"start marker not found: {start_m!r}"
        i_end = len(lines) - 1
        if end_m and end_m != "*":
            for k in range(i_start, len(lines)):
                if end_m in lines[k]: i_end = k; break
            else: return None, f"end marker not found: {end_m!r}"
        return "\n".join(lines[i_start:i_end + 1]), None
    m = re.match(r"^(\d+)?\s*-\s*(\d+)?$", spec)
    if m:
        a = int(m.group(1)) if m.group(1) else 1
        b = int(m.group(2)) if m.group(2) else len(lines)
    elif spec.isdigit():
        a = b = int(spec)
    else:
        return None, f"bad range spec: {spec!r}"
    a = max(1, a); b = min(len(lines), b)
    if a > b: return None, f"empty range {a}-{b}"
    return "\n".join(lines[a - 1:b]), None

# --- Backups ----------------------------------------------------------------
def make_backup(p, keep):
    """Convention: duplicate file, rename to <name>_v<N><ext>, put in .bak/."""
    bak_dir = p.parent / ".bak"
    bak_dir.mkdir(parents=True, exist_ok=True)
    stem, ext = p.stem, p.suffix
    if not stem:
        stem, ext = p.name, ""
    pat = re.compile("^" + re.escape(stem) + "_v(\\d+)" + re.escape(ext) + "$")
    versions = []
    for f in bak_dir.iterdir():
        if not f.is_file():
            continue
        m = pat.match(f.name)
        if m:
            try:
                versions.append((int(m.group(1)), f))
            except ValueError:
                pass
    versions.sort(key=lambda x: x[0])
    while len(versions) >= keep:
        _, oldest = versions.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass
    next_n = versions[-1][0] + 1 if versions else 1
    dst = bak_dir / (stem + "_v" + str(next_n) + ext)
    shutil.copy2(p, dst)
    return dst

# --- Git --------------------------------------------------------------------
def git_root(start):
    try:
        r = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 else None

def git_push(root, touched_paths):
    out = [("head", f"▸ git @ {root}")]
    rel = []
    for p in touched_paths:
        try: rel.append(str(Path(p).resolve().relative_to(root)))
        except ValueError: pass
    if not rel:
        out.append(("muted", "   • nothing to stage")); return out

    def run(args):
        try:
            return subprocess.run(args, cwd=str(root), capture_output=True,
                                  text=True, timeout=120)
        except Exception as e:
            class _R: returncode = 1; stdout = ""; stderr = str(e)
            return _R()

    r = run(["git", "add", "--"] + rel)
    if r.returncode != 0:
        out.append(("err", f"   ✗ git add: {r.stderr.strip()}")); return out
    out.append(("ok", f"   ✓ staged {len(rel)} file(s)"))

    r = run(["git", "commit", "-m", "psedit: automated update"])
    c = (r.stdout + r.stderr).lower()
    if r.returncode == 0:
        out.append(("ok", "   ✓ committed"))
    elif "nothing to commit" in c or "no changes added" in c:
        out.append(("muted", "   • nothing to commit")); return out
    else:
        out.append(("err", f"   ✗ commit: {(r.stderr or r.stdout).strip()}"))
        return out

    r = run(["git", "push"])
    out.append(("err", f"   ✗ push: {(r.stderr or r.stdout).strip()}")
               if r.returncode else ("ok", "   ✓ pushed"))
    return out

SELF_PATH = Path(__file__).resolve()

# ──────────────────────────────────────────────────────────────────────────────
#  PLAN BUILDER
# ──────────────────────────────────────────────────────────────────────────────
def build_plan(script, safe_mode=False):
    log = []
    actions = []
    if not safe_mode:
        for r in script.run_blocks: actions.append((r.line, "run", r))
    else:
        for r in script.run_blocks:
            log.append(("muted", f"safe mode: skipping run block at line {r.line}"))
    for b in script.blocks:      actions.append((b.line, "edit", b))
    for f in script.find_blocks: actions.append((f.line, "find", f))
    for c in script.copy_blocks: actions.append((c.line, "copy", c))
    for t in script.tree_blocks: actions.append((t.line, "tree", t))
    for n in script.notify_blocks: actions.append((n.line, "notify", n))
    for u in script.update_blocks: actions.append((u.line, "update", u))
    actions.sort(key=lambda x: x[0])

    steps = []
    fatal = 0

    for kind, obj in [(k, o) for _, k, o in actions]:

        if kind == "edit":
            b = obj
            p, err = safe_path(b.path)
            if b.kind == "xlsx":
                step = PlanStep(kind="office", line=b.line, path=str(p or b.path))
                step.office_kind = "xlsx"
                if err:
                    step.fatal = True; step.warnings.append(err); fatal += 1
                    steps.append(step); continue
                if not p.exists():
                    step.fatal = True
                    step.warnings.append("file not found")
                    fatal += 1; steps.append(step); continue
                for _r in b.reps:
                    key = (_r.old or "").strip()
                    if "!" not in key:
                        step.warnings.append("bad cell ref (need Sheet!A1): " + key[:40])
                        if script.stop_on_err:
                            step.fatal = True; fatal += 1
                        continue
                    sheet, cell = key.rsplit("!", 1)
                    step.office_edits.append({
                        "sheet": sheet.strip(),
                        "cell": cell.strip(),
                        "value": _r.new.strip(),
                    })
                step.label = "XLSX  " + p.name + "  (" + str(len(step.office_edits)) + " cells)"
                steps.append(step); continue
            if b.kind == "docx":
                step = PlanStep(kind="office", line=b.line, path=str(p or b.path))
                step.office_kind = "docx"
                if err:
                    step.fatal = True; step.warnings.append(err); fatal += 1
                    steps.append(step); continue
                if not p.exists():
                    step.fatal = True
                    step.warnings.append("file not found")
                    fatal += 1; steps.append(step); continue
                for _r in b.reps:
                    if not _r.old:
                        step.warnings.append("empty find skipped")
                        continue
                    step.office_edits.append({
                        "find": _r.old,
                        "replace": _r.new,
                        "match_case": False,
                    })
                step.label = "DOCX  " + p.name + "  (" + str(len(step.office_edits)) + " find/replace)"
                steps.append(step); continue

            step = PlanStep(kind="edit", line=b.line, path=str(p or b.path))
            if err:
                step.fatal = True; step.warnings.append(err); fatal += 1
                steps.append(step); continue

            if not p.exists():
                init_reps   = [r for r in b.reps if r.old == ""]
                search_reps = [r for r in b.reps if r.old != ""]
                if search_reps and not init_reps and b.reps:
                    step.fatal = True
                    step.warnings.append("file not found (leave psfrom:: empty to create)")
                    fatal += 1
                else:
                    step.is_new_file = True
                    step.new_content = "\n".join(r.new for r in init_reps) if init_reps else ""
                    n = len(step.new_content.encode())
                    step.label = f"CREATE  {p.name}  ({n} B)"
                steps.append(step); continue

            if not p.is_file():
                step.fatal = True
                step.warnings.append("path exists but is not a regular file")
                fatal += 1; steps.append(step); continue

            try:
                text, bom, crlf = read_text(p)
            except Exception as e:
                step.fatal = True; step.warnings.append(f"read: {e}")
                fatal += 1; steps.append(step); continue

            step.old_content = text
            step.bom = bom; step.crlf = crlf
            try:
                step.expected_sha256 = sha256_bytes(p.read_bytes())
            except Exception as e:
                step.fatal = True
                step.warnings.append(f"hash: {e}")
                fatal += 1
                steps.append(step)
                continue
            new_text = text

            if b.regex and len(text) > MAX_REGEX_BYTES:
                step.fatal = True
                step.warnings.append(f"regex subject too large ({len(text)} B)")
                fatal += 1; steps.append(step); continue

            for j, r in enumerate(b.reps, 1):
                if r.old == "":
                    step.warnings.append(f"#{j}: empty psfrom skipped"); continue
                if b.regex:
                    try:
                        pattern = re.compile(r.old, re.MULTILINE | re.DOTALL)
                    except re.error as e:
                        step.warnings.append(f"#{j}: bad regex — {e}")
                        step.fatal = True; fatal += 1; continue
                    try:
                        new_text, n = pattern.subn(r.new, new_text)
                    except re.error as e:
                        step.warnings.append(f"#{j}: bad replacement — {e}")
                        step.fatal = True; fatal += 1; continue
                    if n == 0:
                        step.missing.append((j, r.old.split("\n")[0][:60]))
                        if script.stop_on_err: fatal += 1
                        step.fatal = step.fatal or script.stop_on_err
                        continue
                    step.matches.append((j, n, r.old.split("\n")[0][:60]))
                else:
                    n = new_text.count(r.old)
                    if n == 0:
                        step.missing.append((j, r.old.split("\n")[0][:60]))
                        if script.stop_on_err: fatal += 1
                        step.fatal = step.fatal or script.stop_on_err
                        continue
                    new_text = new_text.replace(r.old, r.new)
                    step.matches.append((j, n, r.old.split("\n")[0][:60]))

            step.new_content = new_text
            step.label = (f"EDIT  {p.name}  "
                          f"({len(step.matches)} hit, {len(step.missing)} miss)")
            steps.append(step)

        elif kind == "copy":
            c = obj
            p, err = safe_path(c.path)
            step = PlanStep(kind="copy", line=c.line, path=str(p or c.path))
            if err:
                step.fatal = script.stop_on_err
                if step.fatal: fatal += 1
                step.warnings.append(err); steps.append(step); continue
            if not p.exists():
                step.fatal = script.stop_on_err
                if step.fatal: fatal += 1
                step.warnings.append("file not found"); steps.append(step); continue
            if not p.is_file():
                step.fatal = True; fatal += 1
                step.warnings.append("not a regular file"); steps.append(step); continue
            try:
                text, _, _ = read_text(p)
            except Exception as e:
                step.fatal = True; fatal += 1
                step.warnings.append(f"read: {e}"); steps.append(step); continue
            slice_, err = extract_range(text, c.range_spec)
            if err:
                step.fatal = script.stop_on_err
                if step.fatal: fatal += 1
                step.warnings.append(err); steps.append(step); continue
            step.copy_payload = f"# === {p} ===\n{slice_}"
            step.copy_bytes = len(slice_.encode())
            step.copy_lines = slice_.count("\n") + 1
            rng = f" [{c.range_spec[:24]}]" if c.range_spec else ""
            step.label = f"COPY  {p.name}{rng}  ({step.copy_bytes} B)"
            steps.append(step)

        elif kind == "find":
            f = obj
            p, err = safe_path(f.path)
            step = PlanStep(kind="find", line=f.line, path=str(p or f.path))
            if err:
                step.fatal = script.stop_on_err
                if step.fatal: fatal += 1
                step.warnings.append(err); steps.append(step); continue
            if not p.exists():
                step.fatal = script.stop_on_err
                if step.fatal: fatal += 1
                step.warnings.append("file not found"); steps.append(step); continue
            try:
                text, _, _ = read_text(p)
            except Exception as e:
                step.fatal = True; fatal += 1
                step.warnings.append(f"read: {e}"); steps.append(step); continue
            lines = text.split("\n")
            step.find_source = lines
            step.find_hits = [(i, ln) for i, ln in enumerate(lines, 1)
                              if f.query in ln]
            step.label = f"FIND  {p.name}  ({len(step.find_hits)} hit)"
            steps.append(step)

        elif kind == "run":
            r = obj
            first = r.cmd.split("\n", 1)[0][:60]
            tag = "ADMIN" if r.admin else "RUN"
            vis_tag = " visible" if getattr(r, "visible", False) else ""
            step = PlanStep(kind="run", line=r.line, cmd=r.cmd, admin=r.admin, mode=r.mode,
                            session_id=script.session_id,
                            visible=getattr(r, "visible", False),
                            eta=getattr(r, "eta", 0),
                            label=f"{tag} [{r.mode}]{vis_tag}  {first}")
            steps.append(step)

        elif kind == "notify":
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
                            tree_root=str(p or t.root), tree_entries=t.entries)
            if err:
                step.fatal = True; fatal += 1
                step.warnings.append(err)
            step.label = f"TREE  {Path(step.tree_root).name}/  ({len(t.entries)} entries)"
            steps.append(step)

    for step in steps:
        if not step.job_id:
            step.job_id = "job_" + uuid.uuid4().hex
        step.request_id = script.request_id
        if not step.session_id:
            step.session_id = script.session_id
    return steps, fatal, log


# ──────────────────────────────────────────────────────────────────────────────
#  PLAN EXECUTION — no confirmation gate, just do it. Roll back on fatal.
# ──────────────────────────────────────────────────────────────────────────────
def execute_plan(plan, script, dry_run, force_bak, force_push,
                 stream_cb, copy_cb, cancel_event, progress_cb=None):
    log = []
    cb   = script.create_bak if force_bak is None else force_bak
    keep = script.bak_keep
    gp   = script.git_push   if force_push is None else force_push

    snapshots = {}
    written   = []
    created_dirs = []
    git_paths = set()
    fatal = False
    run_results = []

    def snapshot(path_str, was_new):
        if path_str in snapshots: return
        if was_new: snapshots[path_str] = None
        else:
            try: snapshots[path_str] = Path(path_str).read_bytes()
            except Exception: snapshots[path_str] = None

    def mkdirs_tracked(d: Path):
        if d.exists(): return
        to_make = []
        cur = d
        while not cur.exists() and cur != cur.parent:
            to_make.append(cur)
            cur = cur.parent
        d.mkdir(parents=True, exist_ok=True)
        for c in to_make:
            if c.exists(): created_dirs.append(c)

    total = len(plan)

    for idx, step in enumerate(plan, 1):
        if cancel_event.is_set():
            log.append(("warn", f"[{idx}/{total}]  cancelled"))
            fatal = True; break

        if progress_cb:
            try:
                progress_cb(idx, total, step.label)
            except Exception:
                pass
        log.append(("head", f"[{idx}/{total}]  {step.label}"))
        for w in step.warnings:
            log.append(("warn", f"   ⚠ {w}"))

        if step.kind == "edit":
            for j, n, prev in step.matches:
                log.append(("ok", f"   ✓ #{j}: {n}× ({prev!r})"))
            for j, prev in step.missing:
                log.append(("warn", f"   ⚠ #{j}: not found ({prev!r})"))

            if step.fatal:
                for w in step.warnings:
                    log.append(("err", f"   ✗ {w}"))
                fatal = True
                if script.stop_on_err:
                    log.append(("err", "   → stop.on.error: aborting"))
                    break
                log.append(("blank", "")); continue

            if dry_run:
                if step.old_content != step.new_content:
                    diff = list(difflib.unified_diff(
                        step.old_content.splitlines(),
                        step.new_content.splitlines(),
                        fromfile=f"a/{Path(step.path).name}",
                        tofile=f"b/{Path(step.path).name}",
                        lineterm="", n=2))
                    if diff: log.append(("diff", "\n".join(diff)))
                log.append(("info", "   [dry-run] would write"))
                log.append(("blank", "")); continue

            p = Path(step.path)
            snapshot(step.path, step.is_new_file)

            if not step.is_new_file and step.old_content == step.new_content:
                try:
                    current_sha256 = sha256_bytes(p.read_bytes())
                except Exception as e:
                    log.append(("err", f"   ✗ precondition read: {e}"))
                    fatal = True
                    if script.stop_on_err: break
                    continue
                if step.expected_sha256 and current_sha256 != step.expected_sha256:
                    log.append(("err", "   ✗ stale precondition: file changed after planning"))
                    log.append(("err", f"      expected_sha256={step.expected_sha256}"))
                    log.append(("err", f"      current_sha256 ={current_sha256}"))
                    fatal = True
                    if script.stop_on_err: break
                    continue
                log.append(("muted", "   • no changes"))
                log.append(("blank", "")); continue

            try:
                mkdirs_tracked(p.parent)
                if cb and not step.is_new_file:
                    try:
                        bak = make_backup(p, keep)
                        log.append(("ok", f"   ✓ backup → .bak/{bak.name}"))
                    except Exception as e:
                        log.append(("err", f"   ✗ backup failed: {e}"))
                        fatal = True
                        if script.stop_on_err: break
                        continue
                if not step.is_new_file:
                    try:
                        current_sha256 = sha256_bytes(p.read_bytes())
                    except Exception as e:
                        log.append(("err", f"   ✗ precondition read: {e}"))
                        fatal = True
                        if script.stop_on_err: break
                        continue
                    if step.expected_sha256 and current_sha256 != step.expected_sha256:
                        log.append(("err", "   ✗ stale precondition: file changed after planning"))
                        log.append(("err", f"      expected_sha256={step.expected_sha256}"))
                        log.append(("err", f"      current_sha256 ={current_sha256}"))
                        fatal = True
                        if script.stop_on_err: break
                        continue
                write_text(p, step.new_content, step.bom, step.crlf)
                written.append(step.path)
                git_paths.add(str(p.resolve()))
                log.append(("ok", "   ✓ written"))
            except Exception as e:
                log.append(("err", f"   ✗ write: {e}"))
                fatal = True
                if script.stop_on_err: break
            log.append(("blank", ""))

        elif step.kind == "copy":
            if step.fatal:
                fatal = True
                if script.stop_on_err:
                    log.append(("err", "   → stop.on.error: aborting")); break
                log.append(("blank", "")); continue
            if dry_run:
                log.append(("info", f"   [dry-run] would copy ({step.copy_bytes} B)"))
                log.append(("blank", "")); continue
            copy_cb(step.copy_payload)
            log.append(("ok", f"   ✓ copied to clipboard ({step.copy_bytes} B, "
                              f"{step.copy_lines} lines)"))
            log.append(("blank", ""))

        elif step.kind == "find":
            if step.fatal:
                fatal = True
                if script.stop_on_err:
                    log.append(("err", "   → stop.on.error: aborting")); break
                log.append(("blank", "")); continue
            if not step.find_hits:
                log.append(("warn", "   ⚠ no matches"))
                log.append(("blank", "")); continue
            log.append(("ok", f"   ✓ {len(step.find_hits)} match(es)"))
            for i, _ in step.find_hits:
                lo = max(1, i - 1); hi = min(len(step.find_source), i + 1)
                for n in range(lo, hi + 1):
                    marker = "▶" if n == i else " "
                    log.append(("info", f"   {marker} {n:>5}: {step.find_source[n-1]}"))
                log.append(("blank", ""))

        elif step.kind == "office":
            if step.fatal:
                fatal = True
                if script.stop_on_err:
                    log.append(("err", "   \u2192 stop.on.error: aborting")); break
                log.append(("blank", "")); continue
            if dry_run:
                log.append(("info", f"   [dry-run] would {step.office_kind} edit {step.path}"))
                log.append(("blank", "")); continue
            p = Path(step.path)
            snapshot(step.path, False)
            if cb:
                try:
                    _bak = make_backup(p, keep)
                    log.append(("ok", "   backup -> .bak/" + _bak.name))
                except Exception as _e:
                    log.append(("err", "   backup failed, aborting: " + str(_e)))
                    fatal = True
                    if script.stop_on_err: break
                    log.append(("blank", "")); continue
            import tempfile as _tf, json as _json, subprocess as _sp
            _tmpdir = Path(_tf.gettempdir())
            _tf_edits = _tmpdir / ("psedit_office_" + uuid.uuid4().hex[:8] + ".json")
            try:
                payload = {"kind": step.office_kind, "edits": step.office_edits}
                _tf_edits.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                _cands = []
                try:
                    _cands.append(str(SELF_PATH.parent / "lib" / "office_edit.py"))
                except Exception:
                    pass
                try:
                    _exe = Path(sys.executable).resolve()
                    _cands.append(str(_exe.parent / "lib" / "office_edit.py"))
                    _cands.append(str(_exe.parent.parent / "lib" / "office_edit.py"))
                except Exception:
                    pass
                _cands.append(r"C:\Users\HP\Downloads\PSEDIT\lib\office_edit.py")
                _script = next((c for c in _cands if Path(c).exists()), None)
                if _script is None:
                    raise IOError("office_edit.py not found; tried: " + " | ".join(_cands))
                if not Path(_script).exists():
                    raise IOError("office_edit.py not found at " + _script)
                _py = "C:\\Python314\\python.exe"
                if not Path(_py).exists():
                    _py = sys.executable
                Q = chr(34)
                CRLF = chr(13) + chr(10)
                _logfile = _tmpdir / ("psedit_office_" + uuid.uuid4().hex[:8] + ".out")
                _batfile = _tmpdir / ("psedit_office_" + uuid.uuid4().hex[:8] + ".bat")
                _preview = (step.office_kind.upper() + " " + Path(step.path).name)[:70]
                _bat_parts = [
                    "@echo off",
                    "title PSEdit - " + _preview,
                    Q + _py + Q + " " + Q + _script + Q + " " + Q + step.path + Q + " " + Q + str(_tf_edits) + Q + " --validate > " + Q + str(_logfile) + Q + " 2>&1",
                    "set RC=%ERRORLEVEL%",
                    "type " + Q + str(_logfile) + Q,
                    "echo.",
                    "echo -- PSEdit exit: %RC% --",
                    "if not " + Q + "%RC%" + Q + "==" + Q + "0" + Q + " (",
                    "    echo.",
                    "    echo Press any key to close...",
                    "    pause > nul",
                    ")",
                    "exit /b %RC%",
                ]
                _batfile.write_bytes((CRLF.join(_bat_parts) + CRLF).encode("utf-8"))
                if stream_cb:
                    stream_cb("info", "   running visible: " + _py + " " + _script)
                _creation = getattr(_sp, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0
                _proc = _sp.Popen(["cmd", "/c", str(_batfile)], creationflags=_creation)
                _proc.wait()
                rc = _proc.returncode
                try:
                    if _logfile.exists():
                        _raw = _logfile.read_text(encoding="utf-8", errors="replace")
                        for _ln in _raw.split(chr(10)):
                            _ln2 = _ln.rstrip(chr(13))
                            if _ln2 and stream_cb:
                                stream_cb("stream", "   " + _ln2)
                except Exception:
                    pass
                try:
                    _batfile.unlink(missing_ok=True)
                    _logfile.unlink(missing_ok=True)
                except Exception:
                    pass
                _office_out = []
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
                written.append(step.path)
                git_paths.add(str(p.resolve()))
                if rc == 0:
                    log.append(("ok", f"   \u2713 {step.office_kind} edits applied and validated"))
                else:
                    log.append(("err", f"   \u2717 {step.office_kind} edit failed (rc={rc})"))
                    if _office_out:
                        for _o in _office_out[-10:]:
                            log.append(("err", "     " + _o))
                    fatal = True
                    if script.stop_on_err: break
            except Exception as e:
                log.append(("err", f"   \u2717 office error: {e}"))
                fatal = True
                if script.stop_on_err: break
            finally:
                try: _tf_edits.unlink(missing_ok=True)
                except Exception: pass
            log.append(("blank", ""))

        elif step.kind == "notify":
            if dry_run:
                log.append(("info", "   [dry-run] would notify: " + step.cmd[:60]))
                log.append(("blank", "")); continue
            _title = "PSEdit — AI needs input"
            _body = step.cmd
            _ok, _m = send_toast(_title, _body, parent_widget=None, on_click=None)
            if not _ok:
                _ok, _m = _notify_via_powershell(_title, _body)
            log.append(("ok" if _ok else "warn",
                        "   notification via " + _m + ("" if _ok else " (all methods failed)")))
            log.append(("blank", ""))

        elif step.kind == "update":
            if dry_run:
                log.append(("info", "   [dry-run] would rebuild"))
                log.append(("blank", "")); continue
            _helper = Path(tempfile.gettempdir()) / ("psedit_update_" + uuid.uuid4().hex[:8] + ".py")
            _hb = []
            _hb.append("import subprocess, shutil, time")
            _hb.append("from pathlib import Path")
            _hb.append("time.sleep(2)")
            _hb.append("for n in ('brave.exe', 'PseDIT.exe', 'py.exe'):")
            _hb.append("    subprocess.run(['taskkill', '/F', '/IM', n], capture_output=True)")
            _hb.append("time.sleep(2)")
            _hb.append("root = Path(r'C:/Users/HP/Downloads/PSEDIT')")
            _hb.append("bak = root / 'dist' / '.bak'")
            _hb.append("bak.mkdir(parents=True, exist_ok=True)")
            _hb.append("src = root / 'dist' / 'PseDIT.exe'")
            _hb.append("dst = bak / 'PseDIT_prev.exe'")
            _hb.append("if src.exists():")
            _hb.append("    shutil.copy2(str(src), str(dst))")
            _hb.append("subprocess.run(['C:/Python314/python.exe', '-m', 'PyInstaller', '--clean', 'PseDIT_v15.spec'], cwd=str(root))")
            _hb.append("time.sleep(2)")
            _hb.append("subprocess.Popen(['C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe'])")
            _helper.write_text(chr(10).join(_hb), encoding="utf-8")
            _pyw = r"C:/Python314/pythonw.exe"
            if not Path(_pyw).exists():
                _pyw = r"C:/Python314/python.exe"
            _creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
            try:
                subprocess.Popen([_pyw, str(_helper)], creationflags=_creation, close_fds=True)
                log.append(("ok", "   update helper launched, this window will close"))
            except Exception as _e:
                log.append(("err", "   update launch failed: " + str(_e)))
                fatal = True
                if script.stop_on_err: break
            log.append(("blank", ""))

        elif step.kind == "run":
            if dry_run:
                log.append(("info", "   [dry-run] would execute"))
                log.append(("blank", "")); continue
            ok, run_result = _execute_run(step, stream_cb, cancel_event, log)
            run_results.append(run_result)
            if not ok and script.stop_on_err:
                fatal = True; break

        elif step.kind == "tree":
            if step.fatal:
                fatal = True
                if script.stop_on_err:
                    log.append(("err", "   → aborting")); break
                log.append(("blank", "")); continue
            root = Path(step.tree_root)
            if dry_run:
                for e in step.tree_entries:
                    kind_s = "mkdir" if e.is_dir else "touch"
                    log.append(("info", f"   [dry-run] {kind_s} {e.rel_path}"))
                log.append(("blank", "")); continue
            try:
                mkdirs_tracked(root)
            except Exception as e:
                log.append(("err", f"   ✗ {e}")); fatal = True
                if script.stop_on_err: break
                continue
            for e in step.tree_entries:
                full = root / e.rel_path
                if e.is_dir:
                    try:
                        mkdirs_tracked(full)
                        log.append(("ok", f"   ✓ {e.rel_path}/"))
                    except Exception as ex:
                        log.append(("err", f"   ✗ {e.rel_path}: {ex}"))
                else:
                    if full.exists():
                        log.append(("muted", f"   • {e.rel_path} (exists)")); continue
                    try:
                        mkdirs_tracked(full.parent)
                        write_text(full, e.content, False, False)
                        snapshot(str(full), True)
                        written.append(str(full))
                        git_paths.add(str(full.resolve()))
                        log.append(("ok", f"   ✓ {e.rel_path}"))
                    except Exception as ex:
                        log.append(("err", f"   ✗ {e.rel_path}: {ex}"))
            log.append(("blank", ""))

    if fatal and not dry_run and script.stop_on_err:
        log.append(("head", "═══ ROLLBACK ═══"))
        for path_str in reversed(written):
            try:
                if snapshots.get(path_str) is None:
                    Path(path_str).unlink(missing_ok=True)
                    log.append(("ok", f"   ✓ removed {Path(path_str).name}"))
                else:
                    Path(path_str).write_bytes(snapshots[path_str])
                    log.append(("ok", f"   ✓ restored {Path(path_str).name}"))
            except Exception as e:
                log.append(("err", f"   ✗ {path_str}: {e}"))
        for d in reversed(created_dirs):
            try:
                d.rmdir()
                log.append(("ok", f"   ✓ rmdir {d.name}/"))
            except OSError:
                pass
        log.append(("blank", ""))
        undo_buffer = []
    else:
        undo_buffer = []
        seen = set()
        for path_str in reversed(written):
            if path_str in seen: continue
            seen.add(path_str)
            undo_buffer.append((path_str, snapshots.get(path_str),
                                snapshots.get(path_str) is not None))

    if gp and not dry_run and git_paths and not fatal:
        log.append(("info", "═══ git ═══"))
        roots = {}
        for p in git_paths:
            r = git_root(Path(p).parent)
            if r is None:
                log.append(("warn", f"▸ {p}  (not a git repo)")); continue
            roots.setdefault(r.resolve(), []).append(p)
        for r, paths in roots.items():
            log.extend(git_push(r, paths))
        log.append(("blank", ""))
    elif gp and dry_run:
        log.append(("info", "[dry-run] would push"))
        log.append(("blank", ""))

    if fatal:
        log.append(("err", "✗ aborted" + (" (rolled back)" if not dry_run else "")))
        return False, undo_buffer, log, run_results
    log.append(("ok", "✔ done"))
    return True, undo_buffer, log, run_results


_PYWORKER = {"proc": None, "lock": None, "py": None}


def _find_python_exe():
    for cand in (r"C:\Python314\python.exe",):
        try:
            if Path(cand).exists():
                return cand
        except Exception:
            pass
    return shutil.which("python")


def _get_pyworker():
    if _PYWORKER["proc"] is not None and _PYWORKER["proc"].poll() is None:
        return _PYWORKER["proc"]
    if _PYWORKER["lock"] is None:
        _PYWORKER["lock"] = threading.Lock()
    with _PYWORKER["lock"]:
        if _PYWORKER["proc"] is not None and _PYWORKER["proc"].poll() is None:
            return _PYWORKER["proc"]
        py = _PYWORKER["py"] or _find_python_exe()
        _PYWORKER["py"] = py
        if not py:
            return None
        worker = Path(__file__).resolve().parent / "lib" / "pyworker.py"
        if not worker.exists():
            return None
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        try:
            proc = subprocess.Popen(
                [py, "-u", str(worker)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creation,
            )
        except Exception:
            return None
        _PYWORKER["proc"] = proc
        return proc


def _is_py_script_command(cmd):
    if not cmd:
        return False, None
    s = cmd.strip()
    for ch in ("&", "|", ">", "<", ";", "(", ")"):
        if ch in s:
            return False, None
    import re as _re
    m = _re.match(
        r'^(?:py\s+-3(?:\.\d+)?|"[^"]*python[^"]*\.exe"|\S*python\.exe)\s+'
        r'(?:"([^"]+\.py)"|([^\s]+\.py))(?:\s+(.*))?$',
        s,
        _re.IGNORECASE,
    )
    if not m:
        return False, None
    target = m.group(1) or m.group(2)
    if not target:
        return False, None
    return True, target


def _execute_run_via_worker(step, stream_cb, cancel_event, log, target):
    started = time.time()
    cwd = str(Path.cwd())
    output_lines = []
    proc = _get_pyworker()
    if proc is None:
        log.append(("warn", "   worker unavailable, falling back to subprocess"))
        return None
    try:
        proc.stdin.write("__RUN__ " + target + "\n")
        proc.stdin.flush()
    except Exception as e:
        log.append(("err", f"   worker write failed: {e}"))
        _PYWORKER["proc"] = None
        return None
    rc = None
    deadline = time.time() + MAX_RUN_SECONDS
    while True:
        if cancel_event.is_set():
            log.append(("warn", "   cancelled"))
            try:
                proc.terminate()
            except Exception:
                pass
            _PYWORKER["proc"] = None
            return False, {
                "id": uuid.uuid4().hex,
                "status": "cancelled",
                "command": step.cmd,
                "cwd": cwd,
                "exit_code": None,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time())),
                "duration_seconds": round(time.time() - started, 3),
                "output": "\n".join(output_lines),
            }
        if time.time() > deadline:
            log.append(("warn", f"   timeout after {MAX_RUN_SECONDS}s"))
            try:
                proc.terminate()
            except Exception:
                pass
            _PYWORKER["proc"] = None
            return False, {
                "id": uuid.uuid4().hex,
                "status": "timeout",
                "command": step.cmd,
                "cwd": cwd,
                "exit_code": None,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time())),
                "duration_seconds": round(time.time() - started, 3),
                "output": "\n".join(output_lines),
            }
        line = proc.stdout.readline()
        if not line:
            log.append(("err", "   worker died mid-job"))
            _PYWORKER["proc"] = None
            return None
        stripped = line.rstrip("\r\n")
        if stripped.startswith("__PSEdit_WORKER_DONE__ "):
            try:
                rc = int(stripped.split()[-1])
            except Exception:
                rc = -1
            break
        if stream_cb:
            stream_cb("stream", "   " + stripped)
        output_lines.append(stripped)
    finished = time.time()
    status = "success" if rc == 0 else "failed"
    log.append(("ok" if rc == 0 else "warn",
                f"   {'OK' if rc == 0 else 'FAIL'} exit {rc} (worker)"))
    result = {
        "id": uuid.uuid4().hex,
        "job_id": getattr(step, "job_id", "") or ("job_" + uuid.uuid4().hex),
        "request_id": getattr(step, "request_id", ""),
        "session_id": getattr(step, "session_id", ""),
        "status": status,
        "mode": getattr(step, "mode", "concurrent"),
        "admin": False,
        "command": step.cmd,
        "cwd": cwd,
        "exit_code": rc,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished)),
        "duration_seconds": round(finished - started, 3),
        "output": "\n".join(output_lines),
        "via_worker": True,
    }
    return rc == 0, result


def _notify_via_powershell(title, msg):
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
        "$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>" + tx + "</text><text>" + mx + "</text></binding></visual></toast>');"
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


def _execute_run_visible(step, log):
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

def _execute_run(step, stream_cb, cancel_event, log):
    rb_cmd = step.cmd
    rb_admin = step.admin
    if getattr(step, "visible", False) and not rb_admin:
        return _execute_run_visible(step, log)
    _is_py, _py_target = _is_py_script_command(rb_cmd)
    if _is_py and not rb_admin:
        _routed = _execute_run_via_worker(step, stream_cb, cancel_event, log, _py_target)
        if _routed is not None:
            return _routed
    started = time.time()
    output_lines = []
    cwd = str(Path.cwd())
    status = "failed"
    rc = None

    def emit_line(line):
        clean = line.rstrip("\r\n")
        if clean:
            output_lines.append(clean)
            if stream_cb:
                stream_cb("stream", "   " + clean)

    if rb_admin and sys.platform.startswith("win"):
        token = uuid.uuid4().hex[:8]
        tmpdir = Path(tempfile.gettempdir()) / f"psedit_run_{token}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        out_file = tmpdir / "out.txt"
        done_file = tmpdir / "done.txt"
        batch = tmpdir / "run.bat"
        batch.write_text(
            "@echo off\r\n"
            f"({rb_cmd}) > \"{out_file}\" 2>&1\r\n"
            f"echo %ERRORLEVEL% > \"{done_file}\"\r\n",
            encoding="utf-8",
        )
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "cmd.exe", f'/c "{batch}"', None, 1)
            if ret <= 32:
                log.append(("err", f"   ✗ ShellExecute failed ({ret})"))
                status = "uac_failed"
            else:
                start = time.time(); done = False
                while time.time() - start < MAX_RUN_SECONDS:
                    if done_file.exists(): done = True; break
                    if cancel_event.is_set(): break
                    time.sleep(0.4)
                if not done:
                    status = "cancelled" if cancel_event.is_set() else "timeout"
                    log.append(("warn", "   ⚠ UAC cancelled or timed out"))
                else:
                    try:
                        rc = int((done_file.read_text() or "0").strip())
                    except Exception:
                        rc = -1
                    status = "success" if rc == 0 else "failed"
                    log.append(("ok" if rc == 0 else "warn",
                                f"   {'✓' if rc == 0 else '⚠'} exit {rc} (elevated)"))
                    if out_file.exists():
                        for line in out_file.read_text(errors="replace").splitlines():
                            emit_line(line)
        except Exception as e:
            status = "failed"
            log.append(("err", f"   ✗ {e}"))
        finally:
            try: shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception: pass
    elif rb_admin:
        try:
            proc = subprocess.Popen(
                ["pkexec", "sh", "-c", rb_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            for line in iter(proc.stdout.readline, ""):
                if cancel_event.is_set():
                    proc.terminate(); break
                emit_line(line)
            proc.wait()
            rc = proc.returncode
            status = "success" if rc == 0 else "failed"
            log.append(("ok" if rc == 0 else "warn",
                        f"   {'✓' if rc == 0 else '⚠'} exit {rc} (elevated)"))
        except Exception as e:
            status = "failed"
            log.append(("err", f"   ✗ {e}"))
    else:
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        try:
            proc = subprocess.Popen(
                rb_cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=creation,
            )
            drain_done = threading.Event()
            def _drain(p=proc):
                try:
                    for ln in iter(p.stdout.readline, ""):
                        emit_line(ln)
                except Exception:
                    pass
                finally:
                    drain_done.set()
            threading.Thread(target=_drain, daemon=True).start()

            deadline = time.time() + MAX_RUN_SECONDS
            while not drain_done.is_set():
                if cancel_event.is_set():
                    proc.terminate(); status = "cancelled"; break
                if time.time() > deadline:
                    proc.terminate()
                    status = "timeout"
                    log.append(("warn", f"   ⚠ exceeded {MAX_RUN_SECONDS}s — killed"))
                    break
                time.sleep(0.1)
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            rc = proc.returncode
            if status not in ("cancelled", "timeout"):
                status = "success" if rc == 0 else "failed"
            log.append(("ok" if rc == 0 else "warn",
                        f"   {'✓' if rc == 0 else '⚠'} exit {rc}"))
        except Exception as e:
            status = "failed"
            log.append(("err", f"   ✗ {e}"))

    finished = time.time()
    log.append(("info", f"   ↩ returned to {cwd}"))
    result = {
        "id": uuid.uuid4().hex,
        "job_id": getattr(step, "job_id", "") or ("job_" + uuid.uuid4().hex),
        "request_id": getattr(step, "request_id", ""),
        "session_id": getattr(step, "session_id", ""),
        "status": status,
        "mode": getattr(step, "mode", "concurrent"),
        "admin": bool(rb_admin),
        "command": rb_cmd,
        "cwd": cwd,
        "exit_code": rc,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished)),
        "duration_seconds": round(finished - started, 3),
        "output": "\n".join(output_lines),
    }
    return status == "success", result


def apply_undo(undo_buffer):
    log = [("head", f"Undoing {len(undo_buffer)} file(s)")]
    for path_str, data, existed in undo_buffer:
        p = Path(path_str)
        try:
            if existed and data is not None:
                p.write_bytes(data)
                log.append(("ok", f"   ✓ restored {p.name}"))
            else:
                if p.exists():
                    p.unlink()
                    log.append(("ok", f"   ✓ removed {p.name}"))
        except Exception as e:
            log.append(("err", f"   ✗ {p.name}: {e}"))
    log.append(("blank", ""))
    return log

# --- Rendering --------------------------------------------------------------
PALETTE = {
    "head":  ("#4FC1FF", True),  "ok":    ("#89D185", False),
    "err":   ("#F87171", False), "warn":  ("#FBBF24", False),
    "info":  ("#75BEFF", False), "muted": ("#808080", False),
    "blank": ("#000000", False), "diff":  ("#D4D4D4", False),
    "stream":("#C8C8D0", False),
}

def _diff_html(diff_text):
    out = []
    for ln in diff_text.split("\n"):
        if ln.startswith("+++") or ln.startswith("---"):   color = "#808080"
        elif ln.startswith("+"):                            color = "#89D185"
        elif ln.startswith("-"):                            color = "#F87171"
        elif ln.startswith("@@"):                           color = "#C586C0"
        else:                                               color = "#808080"
        esc = html.escape(ln).replace(" ", "&nbsp;")
        out.append(f'<div style="color:{color}; white-space:pre; '
                   f'font-family:Consolas,monospace; font-size:11px;">{esc}</div>')
    return "".join(out)

def to_html(entries):
    parts = []
    for kind, text in entries:
        if kind == "blank":
            parts.append("<div>&nbsp;</div>"); continue
        if kind == "diff":
            parts.append(_diff_html(text)); continue
        color, bold = PALETTE.get(kind, ("#D4D4D4", False))
        style = f"color:{color};" + ("font-weight:bold;" if bold else "")
        esc   = html.escape(text).replace(" ", "&nbsp;")
        parts.append(f'<div style="{style}">{esc}</div>')
    return "".join(parts)

# --- Highlighter ------------------------------------------------------------
class Highlighter(QSyntaxHighlighter):
    STATE_EXPECT_PATH = 1

    def __init__(self, doc):
        super().__init__(doc)
        def f(c, b=False, i=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(c))
            if b: fmt.setFontWeight(700)
            if i: fmt.setFontItalic(True)
            return fmt
        self.marker  = f("#C586C0", True)
        self.path    = f("#CE9178")
        self.option  = f("#4EC9B0", True)
        self.comment = f("#6A9955", i=True)

    def highlightBlock(self, text):
        s    = text.strip()
        prev = self.previousBlockState()
        if _RUN_MARK_RE.match(s) or s in _ALL_MARKERS:
            self.setFormat(0, len(text), self.marker)
            self.setCurrentBlockState(
                self.STATE_EXPECT_PATH if s in _PATH_MARKERS else 0)
            return
        if _INLINE_COPY_RE.match(s):
            self.setFormat(0, len(text), self.marker)
            self.setCurrentBlockState(self.STATE_EXPECT_PATH)
            return
        if not s:
            self.setCurrentBlockState(
                prev if prev == self.STATE_EXPECT_PATH else 0)
            return
        if prev == self.STATE_EXPECT_PATH:
            self.setFormat(0, len(text), self.path)
            self.setCurrentBlockState(0)
            return
        if OPTION_RE.match(s):
            self.setFormat(0, len(text), self.option)
        elif s.startswith("#"):
            self.setFormat(0, len(text), self.comment)
        self.setCurrentBlockState(0)

# --- Worker -----------------------------------------------------------------
class Worker(QThread):
    done         = pyqtSignal(object)
    stream       = pyqtSignal(object)
    copy_request = pyqtSignal(str, object)
    progress     = pyqtSignal(int, int, str)

    def __init__(self, script, dry, fb, fp, safe_mode):
        super().__init__()
        self.script, self.dry, self.fb, self.fp = script, dry, fb, fp
        self.safe_mode = safe_mode
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _stream(self, kind, text):
        self.stream.emit((kind, text))

    def _copy(self, payload):
        ev = threading.Event()
        self.copy_request.emit(payload, ev)
        ev.wait(timeout=15)

    def _progress(self, i, total, label):
        self.progress.emit(i, total, label)

    def run(self):
        try:
            log = []
            if not self.script.request_id:
                self.script.request_id = "req_" + uuid.uuid4().hex
            if not self.script.session_id:
                self.script.session_id = "sess_" + uuid.uuid4().hex
            plan, fatal, plan_log = build_plan(self.script, safe_mode=self.safe_mode)
            log.extend(plan_log)

            self._stream("info", f"PLAN  {len(plan)} step(s)"
                                 + (f"  •  {fatal} fatal" if fatal else ""))
            for i, s in enumerate(plan, 1):
                mark = "✗" if s.fatal else " "
                self._stream("head" if not s.fatal else "err",
                             f"  [{i}/{len(plan)}]{mark} {s.label}")
            self._stream("blank", "")

            if fatal and self.script.stop_on_err and not self.dry:
                self._stream("err", "Aborting before any writes (stop.on.error).")
                self._stream("blank", "")
                self.done.emit((False, [], log, []))
                return

            ok, undo, exec_log, run_results = execute_plan(
                plan, self.script, self.dry, self.fb, self.fp,
                stream_cb=self._stream,
                copy_cb=self._copy,
                cancel_event=self._cancel,
                progress_cb=self._progress,
            )
            log.extend(exec_log)
            self.done.emit((ok, undo, log, run_results))
        except Exception:
            self.done.emit((False, [], [("err", traceback.format_exc())]))

# ──────────────────────────────────────────────────────────────────────────────
#  TOAST
# ──────────────────────────────────────────────────────────────────────────────
_TOAST_ERRORS = []

def _try_windows_toasts(title, msg):
    from windows_toasts import Toast, WindowsToaster
    t = WindowsToaster(APP_NAME)
    n = Toast(); n.text_fields = [title, msg]
    t.show_toast(n)

def _try_powershell(title, msg):
    def xesc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;")
                 .replace("'", "&apos;"))
    tx, mx = xesc(title), xesc(msg)
    ps = (
        "$ErrorActionPreference='Stop';"
        "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime];"
        "[void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime];"
        "[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime];"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{tx}</text><text>{mx}</text></binding></visual></toast>');"
        "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($t)"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, timeout=20, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "powershell failed").strip())

def _try_qt_tray(title, msg, parent):
    if parent is None or getattr(parent, "_tray", None) is None:
        raise RuntimeError("no tray icon")
    parent._tray.show()
    parent._tray.showMessage(title, msg, _TRAY_INFO, 8000)

def _try_win11toast(title, msg, on_click):
    from win11toast import toast
    if on_click is not None:
        toast(title, msg, on_click=lambda args: on_click())
    else:
        toast(title, msg)

def _try_win10toast(title, msg, on_click):
    from win10toast_click import ToastNotifier
    ToastNotifier().show_toast(title, msg, duration=8, threaded=True,
                               callback_on_click=on_click)

def _try_plyer(title, msg, on_click):
    from plyer import notification
    notification.notify(title=title, message=msg, timeout=8)

def send_toast(title, msg, parent_widget=None, on_click=None):
    global _TOAST_ERRORS
    _TOAST_ERRORS = []
    attempts = [
        ("windows-toasts",   lambda: _try_windows_toasts(title, msg)),
        ("powershell-winrt", lambda: _try_powershell(title, msg)),
        ("qt-tray",          lambda: _try_qt_tray(title, msg, parent_widget)),
        ("win11toast",       lambda: _try_win11toast(title, msg, on_click)),
        ("win10toast_click", lambda: _try_win10toast(title, msg, on_click)),
        ("plyer",            lambda: _try_plyer(title, msg, on_click)),
    ]
    for name, fn in attempts:
        try:
            fn(); return True, name
        except Exception as e:
            _TOAST_ERRORS.append(f"{name}: {e}")
    return False, "none"

def toast_error_summary():
    return " | ".join(_TOAST_ERRORS) if _TOAST_ERRORS else ""

def make_tray_icon():
    pix = QPixmap(32, 32)
    pix.fill(QColor(59, 130, 246))
    return QIcon(pix)

# ──────────────────────────────────────────────────────────────────────────────
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):     self._items.append(item)
    def count(self):             return len(self._items)
    def itemAt(self, i):         return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i):         return self._items.pop(i) if 0 <= i < len(self._items) else None
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._do_layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):     return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = eff.x(); y = eff.y(); line_h = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h
            if next_x - self._h > eff.right() and line_h > 0:
                x = eff.x(); y = y + line_h + self._v
                next_x = x + hint.width() + self._h
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()

# ──────────────────────────────────────────────────────────────────────────────
DARK_QSS = """
* { font-family: 'Segoe UI Variable', 'Segoe UI', -apple-system, 'Inter', sans-serif; }
QMainWindow, QWidget#root { background:#0E0E10; color:#E8E8E8; }
QWidget#header { background:#131317; border-bottom:1px solid #1F1F24; }
QLabel#appTitle { color:#FFFFFF; font-size:14px; font-weight:600; }
QLabel#appVersion { color:#5A5A66; font-size:11px; }
QLabel#sectionLabel { color:#6E6E78; font-size:10px; font-weight:600;
                      letter-spacing:1.4px; padding:2px 2px 2px 4px; }
QLabel#status { color:#7A7A85; font-size:11px; padding:2px 4px; }

QPlainTextEdit, QTextEdit { background:#111114; color:#DCDCE0;
    border:1px solid #232328; border-radius:8px; padding:10px;
    selection-background-color:#2D5A9E; selection-color:#FFFFFF;
    font-family: 'JetBrains Mono','Cascadia Code','Consolas',monospace; }
QPlainTextEdit:focus, QTextEdit:focus { border-color:#3B82F6; }

QPushButton#primary { background:#3B82F6; color:#FFFFFF; border:none;
    padding:8px 20px; border-radius:6px; font-weight:600; font-size:12px;
    min-height:32px; }
QPushButton#primary:hover { background:#4B8FF6; }
QPushButton#primary:pressed { background:#2B72E6; }
QPushButton#primary:disabled { background:#1E1E24; color:#4A4A52; }

QPushButton#secondary { background:#191920; color:#C8C8D0;
    border:1px solid #26262E; border-radius:6px; padding:7px 14px;
    font-size:12px; min-height:32px; }
QPushButton#secondary:hover { background:#202028; color:#E8E8E8; border-color:#33333C; }
QPushButton#secondary:pressed { background:#161620; }
QPushButton#secondary:disabled { background:#131318; color:#44444E; border-color:#1E1E24; }

QPushButton#undoHot { background:#166534; color:#DCFCE7; border:1px solid #22C55E;
    border-radius:6px; padding:7px 14px; font-size:12px; font-weight:600;
    min-height:32px; }
QPushButton#undoHot:hover { background:#15803D; }

QPushButton#danger { background:#7F1D1D; color:#FEE2E2; border:1px solid #991B1B;
    border-radius:6px; padding:7px 14px; font-size:12px; min-height:32px; }
QPushButton#danger:hover { background:#991B1B; }
QPushButton#danger:disabled { background:#1E1E24; color:#4A4A52; border-color:#1F1F24; }

QPushButton#pill { background:#191920; color:#C8C8D0;
    border:1px solid #26262E; border-radius:13px; padding:4px 12px; font-size:11px; }
QPushButton#pill:hover { background:#23232C; color:#FFFFFF; border-color:#33333C; }

QCheckBox { color:#B8B8C0; spacing:7px; font-size:11px; }
QCheckBox::indicator { width:13px; height:13px; border-radius:3px;
    border:1px solid #33333C; background:#191920; }
QCheckBox::indicator:hover { border-color:#4A4A52; }
QCheckBox::indicator:checked { background:#3B82F6; border-color:#3B82F6; }

QSplitter::handle { background:transparent; }
QSplitter::handle:vertical { height:6px; }
QSplitter::handle:hover { background:#26262E; border-radius:3px; }

QScrollBar:vertical { background:transparent; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#26262E; border-radius:5px; min-height:24px; }
QScrollBar::handle:vertical:hover { background:#33333C; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:transparent; height:10px; margin:0; }
QScrollBar::handle:horizontal { background:#26262E; border-radius:5px; min-width:24px; }
QScrollBar::handle:horizontal:hover { background:#33333C; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }

QToolButton#outCopy { background:rgba(30,30,38,0.92); color:#B8B8C0;
    border:1px solid #26262E; border-radius:11px; padding:3px 10px; font-size:10px; }
QToolButton#outCopy:hover { background:rgba(50,50,60,0.96); color:#FFFFFF; }

QMessageBox { background:#131317; color:#E8E8E8; }
"""

SAMPLE = r'''# Sample PSEdit script — edit, run, scaffold.

psedit::
"C:\Users\PC\Downloads\doomnotes\pubspec.yaml"
psfrom::
version: 1.0.0
psto::
version: 1.0.1

psrun::
git status --short

create.bak    {true}
Git push      {false}
stop.on.error {true}
'''

# ──────────────────────────────────────────────────────────────────────────────
class OutputView(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._copy = QToolButton(self)
        self._copy.setObjectName("outCopy")
        self._copy.setText("Copy")
        self._copy.setCursor(_CURSOR_PT)
        self._copy.setToolTip("Copy all output")
        self._copy.clicked.connect(self._on_copy)
        self._copy.adjustSize()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._copy.adjustSize()
        self._copy.move(self.width() - self._copy.width() - 12, 12)

    def _on_copy(self):
        QApplication.clipboard().setText(self.toPlainText())
        self._copy.setText("Copied")
        QTimer.singleShot(1200, lambda: self._copy.setText("Copy"))

# ──────────────────────────────────────────────────────────────────────────────
class RunJobWindow(QMainWindow):
    finished_result = pyqtSignal(object)

    def __init__(self, run_block, index, total, safe_mode, owner):
        super().__init__(owner)
        self.owner = owner
        self.run_block = run_block
        self.index = index
        self.total = total
        self.safe_mode = safe_mode
        self.run_block_session_id = getattr(run_block, "session_id", "")
        self.worker = None
        self.result = None
        self.setWindowTitle(f"PSEdit — Run {index}/{total}")
        self.resize(560, 430)
        self.setMinimumSize(420, 300)
        self.setStyleSheet(DARK_QSS)

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(14, 14, 14, 14); lay.setSpacing(8)

        title = QLabel(f"PSRUN {index}/{total}  •  {run_block.mode}")
        title.setObjectName("appTitle")
        lay.addWidget(title)
        cmd = QLabel(run_block.cmd.replace("\n", "  ↵  "))
        cmd.setWordWrap(True)
        cmd.setStyleSheet("color:#9A9AA5; font-size:11px;")
        lay.addWidget(cmd)

        self.out = OutputView()
        self.out.setFont(QFont("Consolas", 10))
        lay.addWidget(self.out, 1)

        row = QHBoxLayout(); row.setSpacing(6)
        self.btn_copy = QPushButton("Copy PSResult")
        self.btn_copy.setObjectName("secondary")
        self.btn_copy.clicked.connect(self._copy_result)
        self.btn_copy.setEnabled(False)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondary")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.setEnabled(False)
        row.addWidget(self.btn_copy); row.addWidget(self.btn_cancel); row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.status = QLabel("Starting…")
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        self._start()

    def _append(self, entries):
        self.out.moveCursor(_END)
        self.out.insertHtml(to_html(entries))
        self.out.verticalScrollBar().setValue(self.out.verticalScrollBar().maximum())

    def _start(self):
        script = Script(run_blocks=[self.run_block], stop_on_err=True, session_id=self.run_block_session_id)

        self.worker = Worker(script, False, False, False, safe_mode=self.safe_mode)
        self.worker.stream.connect(lambda payload: self._append([payload]))
        self.worker.done.connect(self._done)
        self.worker.start()

    def _cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.status.setText("Cancelling…")

    def _copy_result(self):
        if not self.result:
            return
        QApplication.clipboard().setText(make_psresult(self.result))
        self.status.setText("PSResult copied.")
        self.btn_copy.setText("Copied")
        QTimer.singleShot(1200, lambda: self.btn_copy.setText("Copy PSResult"))

    def _done(self, payload):
        ok, undo, log, run_results = payload
        self._append(log)
        if run_results:
            self.result = dict(run_results[0])
            self.result["_order"] = self.index
            self.btn_copy.setEnabled(True)
        else:
            self.result = {
                "id": uuid.uuid4().hex,
                "session_id": self.run_block.session_id,
                "status": "skipped",
                "mode": self.run_block.mode,
                "admin": bool(self.run_block.admin),
                "command": self.run_block.cmd,
                "cwd": str(Path.cwd()),
                "exit_code": None,
                "started_at": "",
                "finished_at": "",
                "duration_seconds": 0,
                "output": "",
                "_order": self.index,
            }
        self._append([("blank", ""), ("info", "PSRESULT ready — use Copy PSResult to send the machine-readable result to the AI.")])
        self.status.setText("Finished." if ok else "Finished with errors.")
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.finished_result.emit((self.result, ok))

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            e.ignore()
            return
        super().closeEvent(e)


class NativeBridge(QObject):
    """Chrome Native Messaging transport. stdout is reserved for protocol frames."""
    PROTOCOL = "PSEDIT/2"
    message = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._reader, name="PSEditNativeReader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def send(self, message):
        raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        frame = struct.pack("<I", len(raw)) + raw
        with self._write_lock:
            sys.stdout.buffer.write(frame)
            sys.stdout.buffer.flush()

    def _reader(self):
        fd = sys.stdin.buffer.fileno()
        while not self._stop.is_set():
            try:
                header = os.read(fd, 4)
                if not header or len(header) != 4:
                    self._stop.set()
                    return
                n = struct.unpack("<I", header)[0]
                if n <= 0 or n > MAX_NATIVE_MESSAGE_BYTES:
                    self.send({"v": 1, "type": "error", "error": "invalid native message size"})
                    return
                payload = b""
                while len(payload) < n:
                    chunk = os.read(fd, n - len(payload))
                    if not chunk:
                        self.send({"v": 1, "type": "error", "error": "truncated native message"})
                        return
                    payload += chunk
                msg = json.loads(payload.decode("utf-8"))
                self.message.emit(msg)
            except Exception as e:
                try:
                    self.send({"v": 1, "type": "error", "error": str(e)})
                except Exception:
                    pass
                return

class NativeJob:
    def __init__(self, request_id, session_id, psl):
        self.request_id = request_id
        self.session_id = session_id
        self.psl = psl
        self.script = None
        self.worker = None
        self.state = "QUEUED"
        self.started_at = time.time()
        self.finished_at = None
        self.logs = []
        self.copy_results = []
        self.run_results = []
        self.undo = []
        self.ok = False
        self.plan = []
        self.row_labels = []


def _classify_exit(rc):
    if rc is None:
        return "unknown"
    if rc == 0:
        return "success"
    if rc == 1:
        return "generic-failure"
    if rc == 2:
        return "usage-or-missing-file"
    if rc in (127, 9009):
        return "command-not-found"
    if rc == 5:
        return "permission-denied"
    if rc == -1:
        return "internal"
    return "nonzero-exit"


def _one_line_summary(job, created, written):
    total = len(job.plan)
    succ = sum(1 for s in job.plan if getattr(s, "_ui_state", "") == "DONE")
    fail = sum(1 for s in job.plan if getattr(s, "_ui_state", "") in ("FAILED", "TIMEOUT"))
    dur = round((job.finished_at or time.time()) - job.started_at, 2)
    parts = [str(succ) + "/" + str(total) + " blocks ok"]
    if fail:
        parts.append(str(fail) + " failed")
    if created:
        parts.append(str(len(created)) + " created")
    if written:
        parts.append(str(len(written)) + " written")
    parts.append(str(dur) + "s")
    return ", ".join(parts)


class NativeDashboard(QMainWindow):
    """One native-runtime window with multiple background Worker jobs."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PSEdit {APP_VERSION}")
        self.resize(640, 430)
        self.setMinimumSize(480, 300)
        self.setStyleSheet(DARK_QSS)
        self._native = NativeBridge()
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
            pass

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            self._tray.setIcon(make_tray_icon())
            self._tray.setToolTip(f"{APP_NAME} {APP_VERSION}")
            self._tray.show()

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("PSEdit")
        title.setObjectName("appTitle")
        title.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse if _QT6
            else Qt.TextSelectableByMouse)
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.btn_copy_all = QPushButton("Copy all")
        self.btn_copy_all.setObjectName("pill")
        self.btn_copy_all.setCursor(_CURSOR_PT)
        self.btn_copy_all.setToolTip("Copy every row and log line to the clipboard")
        self.btn_copy_all.clicked.connect(self._copy_all)
        title_row.addWidget(self.btn_copy_all)
        self.btn_clear_done = QPushButton("Clear finished")
        self.btn_clear_done.setObjectName("pill")
        self.btn_clear_done.setCursor(_CURSOR_PT)
        self.btn_clear_done.setToolTip("Remove rows for completed jobs")
        self.btn_clear_done.clicked.connect(self._clear_finished)
        title_row.addWidget(self.btn_clear_done)
        lay.addLayout(title_row)

        self.summary = QLabel("Waiting for a browser request…")
        self.summary.setObjectName("status")
        self.summary.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse if _QT6
            else Qt.TextSelectableByMouse)
        lay.addWidget(self.summary)

        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        self.rows.setContentsMargins(4, 4, 4, 4)
        holder = QWidget(); holder.setLayout(self.rows)

        self.scroll = QScrollArea()
        self.scroll.setWidget(holder)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if _QT6 else Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)

        self.empty = QLabel("No active processes.\n\nPSEdit is connected and waiting for an AI request.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter if _QT6 else Qt.AlignCenter)
        self.empty.setObjectName("status")
        self.empty.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse if _QT6
            else Qt.TextSelectableByMouse)
        self.rows.addWidget(self.empty)

        self._native.message.connect(self._handle_native_message)
        self._native.start()
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(1000)
        self._watchdog.timeout.connect(self._tick)
        self._watchdog.start()
        self._reply({
            "v": 2, "type": "hello", "protocol": "PSEDIT/2", "app": APP_NAME,
            "version": APP_VERSION, "max_parallel_jobs": self._max_parallel,
        })

    def _reply(self, payload):
        try:
            self._native.send(payload)
        except Exception:
            pass

    def _tick(self):
        now = time.time()
        for job in list(self._jobs.values()):
            if job.state in ("RUNNING", "WAITING FOR CONFIRMATION"):
                for step in job.plan:
                    state = getattr(step, "_ui_state", "QUEUED")
                    if state in ("RUNNING", "WAITING FOR CONFIRMATION"):
                        started = getattr(step, "_ui_started_at", None) or job.started_at
                        if now - started > MAX_RUN_SECONDS:
                            step._ui_state = "TIMEOUT"
                            if job.worker is not None and job.worker.isRunning():
                                job.worker.cancel()
                self._update_rows(job)
            if job.state in ("DONE", "FAILED", "CANCELLED") and job.finished_at is not None:
                if now - job.finished_at > 60:
                    self._jobs.pop(job.request_id, None)
                    for lbl in list(job.row_labels):
                        try:
                            lbl.setParent(None)
                            lbl.deleteLater()
                        except Exception:
                            pass
        self._update_summary()

    def _notify(self, title, msg):
        try:
            if getattr(self, "_tray", None) is not None:
                self._tray.showMessage(title, msg, _TRAY_INFO, 6000)
        except Exception:
            pass

    def _clear_finished(self):
        for _jid in list(self._jobs.keys()):
            _j = self._jobs[_jid]
            if _j.state in ("DONE", "FAILED", "CANCELLED"):
                for _lbl in list(_j.row_labels):
                    try:
                        _lbl.setParent(None)
                        _lbl.deleteLater()
                    except Exception:
                        pass
                self._jobs.pop(_jid, None)
        if not self._jobs:
            self.empty.show()
        self._update_summary()

    def _copy_all(self):
        try:
            lines = ["PSEdit " + APP_VERSION, self.summary.text(), ""]
            for job in self._jobs.values():
                lines.append("=== job " + job.request_id + " (" + job.state + ") ===")
                for step in job.plan:
                    state = getattr(step, "_ui_state", "QUEUED")
                    lines.append(f"  [{state}]  {step.label}")
                if job.logs:
                    lines.append("  --- log ---")
                    for kind, text in job.logs[-80:]:
                        lines.append("  " + str(text))
                lines.append("")
            QApplication.clipboard().setText("\n".join(lines))
            self.btn_copy_all.setText("Copied")
            QTimer.singleShot(1200, lambda: self.btn_copy_all.setText("Copy all"))
        except Exception:
            pass

    def _update_rows(self, job):
        labels = job.row_labels
        if not labels:
            for label_text in (s.label or "request" for s in job.plan):
                label = QLabel()
                label.setFont(QFont("Consolas", 10))
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse if _QT6
                    else Qt.TextSelectableByMouse)
                labels.append(label)
                self.rows.insertWidget(self.rows.count() - 1, label)
        now = time.time()
        for i, step in enumerate(job.plan):
            state = getattr(step, "_ui_state", "QUEUED")
            icon = {"DONE": "✓", "FAILED": "✕", "RUNNING": "●", "WAITING FOR CONFIRMATION": "◷", "QUEUED": "…", "CANCELLED": "—", "TIMEOUT": "⏱", "STALLED": "⚠"}.get(state, "·")
            suffix = state
            if state in ("RUNNING", "WAITING FOR CONFIRMATION"):
                started = getattr(step, "_ui_started_at", None)
                if started:
                    e = now - started
                    suffix = f"{state} ({int(e // 60):02d}:{int(e % 60):02d})"
            labels[i].setText(f"{icon}  {step.label:<62}  {suffix}")
        if labels:
            self.empty.hide()

    def _update_summary(self):
        states = [getattr(step, "_ui_state", "QUEUED") for j in self._jobs.values() for step in j.plan]
        active = sum(state in ("RUNNING", "WAITING FOR CONFIRMATION") for state in states)
        queued = sum(state == "QUEUED" for state in states)
        if active or queued:
            self.summary.setText(f"RUNNING {active} PROCESSES…" + (f"   •   {queued} queued" if queued else ""))
            self.empty.hide()
        elif not self._jobs:
            self.summary.setText("Waiting for a browser request…")
            self.empty.show()
        else:
            self.summary.setText("All processes finished.")

    def _handle_native_message(self, msg):
        if not isinstance(msg, dict):
            return
        typ = msg.get("type")
        if typ == "hello":
            self._reply({"v": 2, "type": "ready", "protocol": "PSEDIT/2", "app": APP_NAME,
                         "version": APP_VERSION, "max_parallel_jobs": self._max_parallel,
                         "operations": ["psedit", "pscopy", "psfind", "pstree", "psrun", "psrunadmin", "cancel"]})
        elif typ == "ping":
            self._reply({"v": 2, "type": "pong", "protocol": "PSEDIT/2", "version": APP_VERSION})
        elif typ == "submit":
            self._submit(msg)
        elif typ == "cancel":
            self._cancel_job(str(msg.get("request_id") or ""))

    def _submit(self, msg):
        request_id = str(msg.get("request_id") or uuid.uuid4().hex)
        session_id = str(msg.get("session_id") or uuid.uuid4().hex)
        psl = str(msg.get("payload") or msg.get("psl") or "")
        if not psl.strip():
            self._reply({"v": 2, "type": "result", "request_id": request_id, "session_id": session_id,
                         "status": "rejected", "reason": "empty_psl"})
            return
        if request_id in self._jobs:
            self._reply({"v": 2, "type": "result", "request_id": request_id, "session_id": session_id,
                         "status": "rejected", "reason": "duplicate_request_id"})
            return
        script, errs = parse_script(psl)
        if errs:
            self._reply({"v": 2, "type": "result", "request_id": request_id, "session_id": session_id,
                         "status": "syntax_error", "errors": errs})
            return
        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)
                 + len(script.run_blocks) + len(script.tree_blocks)
                 + len(script.notify_blocks) + len(script.update_blocks))
        if total == 0:
            self._reply({"v": 2, "type": "result", "request_id": request_id, "session_id": session_id,
                         "status": "rejected", "reason": "no_blocks"})
            return
        script.request_id = request_id
        script.session_id = script.session_id or session_id
        job = NativeJob(request_id, session_id, psl)
        job.script = script
        job.plan, fatal, _ = build_plan(script, safe_mode=False)
        for step in job.plan:
            step._ui_state = "QUEUED"
        if fatal and script.stop_on_err:
            for step in job.plan:
                if step.fatal:
                    step._ui_state = "FAILED"
                    break
        self._jobs[request_id] = job
        self._queue.append(request_id)
        self._update_rows(job)
        self._reply({"v": 2, "type": "accepted", "request_id": request_id, "session_id": session_id,
                     "queue_position": len(self._queue) - 1, "active": len(self._active), "max_parallel": self._max_parallel})
        self._pump()

    def _pump(self):
        while len(self._active) < self._max_parallel and self._queue:
            rid = self._queue.pop(0)
            job = self._jobs.get(rid)
            if job is None or job.state != "QUEUED":
                continue
            self._start_job(job)
        self._update_summary()

    def _start_job(self, job):
        job.state = "WAITING FOR CONFIRMATION" if job.script.has_admin() else "RUNNING"
        self._active.add(job.request_id)
        if job.plan:
            job.plan[0]._ui_state = job.state
        self._update_rows(job)
        self._reply({"v": 2, "type": "progress", "request_id": job.request_id, "session_id": job.session_id,
                     "state": job.state, "active": len(self._active)})
        worker = Worker(job.script, False, None, None, safe_mode=False)
        job.worker = worker
        worker.stream.connect(lambda payload, rid=job.request_id: self._on_stream(rid, payload))
        worker.progress.connect(lambda i, total, label, rid=job.request_id: self._on_progress(rid, i, total, label))
        worker.copy_request.connect(lambda payload, ev, rid=job.request_id: self._on_copy(rid, payload, ev))
        worker.done.connect(lambda payload, rid=job.request_id: self._on_done(rid, payload))
        worker.start()

    def _on_progress(self, request_id, index, total, label):
        job = self._jobs.get(request_id)
        if job is None:
            return
        now = time.time()
        for i, step in enumerate(job.plan):
            if i < index - 1:
                step._ui_state = "DONE"
            elif i == index - 1:
                step._ui_state = "WAITING FOR CONFIRMATION" if step.kind == "run" and step.admin else "RUNNING"
                if getattr(step, "_ui_started_at", None) is None:
                    step._ui_started_at = now
            elif getattr(step, "_ui_state", "QUEUED") not in ("FAILED", "CANCELLED"):
                step._ui_state = "QUEUED"
        self._update_rows(job)
        self._update_summary()

    def _on_stream(self, request_id, payload):
        job = self._jobs.get(request_id)
        if job is None:
            return
        job.logs.append(payload)
        if len(job.logs) > 300:
            del job.logs[:-300]

    def _on_copy(self, request_id, payload, ev):
        try:
            job = self._jobs.get(request_id)
            if job is not None:
                job.copy_results.append(str(payload))
        finally:
            ev.set()

    def _on_done(self, request_id, payload):
        job = self._jobs.get(request_id)
        if job is None:
            return
        try:
            ok, undo, log, run_results = payload
        except Exception:
            ok, undo, log, run_results = False, [], [("err", traceback.format_exc())], []
        job.ok = bool(ok)
        job.undo = undo or []
        job.run_results = run_results or []
        job.logs.extend(log or [])
        job.finished_at = time.time()
        job.state = "DONE" if job.ok else "FAILED"
        self._active.discard(request_id)
        for step in job.plan:
            if step._ui_state in ("RUNNING", "WAITING FOR CONFIRMATION", "QUEUED"):
                step._ui_state = "DONE" if job.ok else "FAILED"
        self._update_rows(job)
        self._notify(
            "PSEdit",
            f"{'Done' if job.ok else 'Failed'} in {round((job.finished_at or time.time()) - job.started_at, 1)}s"
        )
        self._reply({
            "v": 2, "type": "result", "protocol": "PSEDIT/2",
            "request_id": request_id, "session_id": job.session_id,
            "status": "success" if job.ok else "failed",
            "psresult": self._make_psresult(job),
            "run_results": job.run_results,
            "copy_results": job.copy_results,
            "undo_count": len(job.undo),
        })
        self._pump()

    def _make_psresult(self, job):
        _created = []
        _written = []
        for _entry in job.undo:
            try:
                _ps, _snap, _existed = _entry
            except Exception:
                continue
            if _existed:
                _written.append(_ps)
            else:
                _created.append(_ps)
        for _r in job.run_results:
            if "output_meaning" not in _r:
                _r["output_meaning"] = _classify_exit(_r.get("exit_code"))
        summary = {
            "blocks_total": len(job.plan),
            "succeeded": sum(1 for _s in job.plan if getattr(_s, "_ui_state", "") == "DONE"),
            "failed": sum(1 for _s in job.plan if getattr(_s, "_ui_state", "") in ("FAILED", "TIMEOUT")),
            "files_created": _created,
            "files_written": _written,
            "rollback": False,
            "one_line": _one_line_summary(job, _created, _written),
        }
        if len(job.run_results) == 1 and not job.copy_results:
            result = dict(job.run_results[0])
            result["request_id"] = job.request_id
            result["session_id"] = job.session_id
            result["summary"] = summary
            return make_psresult(result)
        payload = {
            "request_id": job.request_id,
            "session_id": job.session_id,
            "status": "success" if job.ok else "failed",
            "duration_seconds": round((job.finished_at or time.time()) - job.started_at, 3),
            "summary": summary,
            "run_results": job.run_results,
            "copy_results": job.copy_results,
            "undo_count": len(job.undo),
        }
        return PSRESULT_START + "\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n" + PSRESULT_END

    def _cancel_job(self, request_id):
        job = self._jobs.get(request_id)
        if job is None:
            self._reply({"v": 2, "type": "cancelled", "request_id": request_id, "reason": "unknown_request"})
            return
        if job.state == "QUEUED":
            self._queue = [rid for rid in self._queue if rid != request_id]
            job.state = "CANCELLED"
            self._update_rows(job)
            self._reply({"v": 2, "type": "cancelled", "request_id": request_id, "removed": True})
            self._pump()
            return
        if job.worker is not None and job.worker.isRunning():
            job.worker.cancel()
            self._reply({"v": 2, "type": "cancel_requested", "request_id": request_id})
            return
        self._reply({"v": 2, "type": "cancelled", "request_id": request_id, "removed": False})

    def closeEvent(self, e):
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


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(560, 760)
        self.setMinimumSize(340, 440)
        self.setStyleSheet(DARK_QSS)
        self.worker = None
        self._last_clip = ""
        self._tray = None
        self._last_undo = []
        self._last_psresult = ""
        self._sim_windows = []
        self._sim_results = []
        self._sim_expected = 0
        self._sim_batch_id = ""
        self._native = None
        self._native_queue = []
        self._native_current = None

        root_w = QWidget(); root_w.setObjectName("root")
        self.setCentralWidget(root_w)
        root = QVBoxLayout(root_w)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget(); header.setObjectName("header")
        hl = QHBoxLayout(header); hl.setContentsMargins(14, 10, 14, 10); hl.setSpacing(10)
        title = QLabel("PSEdit"); title.setObjectName("appTitle")
        ver   = QLabel(f"v{APP_VERSION}"); ver.setObjectName("appVersion")
        hl.addWidget(title); hl.addWidget(ver); hl.addStretch(1)

        self.cb_autorun = QCheckBox("Auto-run")
        self.cb_autorun.setToolTip("Run immediately when a complete PSL payload lands in the clipboard")
        hl.addWidget(self.cb_autorun)

        self.cb_return = QCheckBox("Auto-result")
        self.cb_return.setToolTip("Copy the completed PSRESULT automatically when a run finishes")
        hl.addWidget(self.cb_return)

        self.cb_top = QCheckBox("Top")
        self.cb_top.toggled.connect(self._toggle_top)
        hl.addWidget(self.cb_top)

        self.cb_safe = QCheckBox("Safe mode")
        self.cb_safe.setToolTip("Skip psrun/psrunadmin blocks")
        hl.addWidget(self.cb_safe)

        self.cb_bak  = QCheckBox("Backup")
        self.cb_push = QCheckBox("Push")
        hl.addWidget(self.cb_bak); hl.addWidget(self.cb_push)

        self.btn_copy_prompt = QPushButton("Copy Prompt")
        self.btn_copy_prompt.setObjectName("pill")
        self.btn_copy_prompt.setCursor(_CURSOR_PT)
        self.btn_copy_prompt.clicked.connect(self._copy_prompt)
        hl.addWidget(self.btn_copy_prompt)
        root.addWidget(header)

        # ── Content ───────────────────────────────────────────────────────
        content = QWidget()
        cl = QVBoxLayout(content); cl.setContentsMargins(14, 12, 14, 12); cl.setSpacing(6)
        cl.addWidget(self._section_label("SCRIPT"))

        self.splitter = QSplitter(_ORIENT_V)
        cl.addWidget(self.splitter, 1)

        ed_panel = QWidget()
        ed_lay = QVBoxLayout(ed_panel); ed_lay.setContentsMargins(0,0,0,0); ed_lay.setSpacing(4)
        self.editor = QPlainTextEdit(); self.editor.setPlainText(SAMPLE)
        self.editor.setFont(self._mono(11)); self.editor.setTabStopDistance(32)
        self.hl = Highlighter(self.editor.document())
        self.editor.textChanged.connect(self._on_editor_changed)
        ed_lay.addWidget(self.editor, 1)

        out_panel = QWidget()
        out_lay = QVBoxLayout(out_panel); out_lay.setContentsMargins(0,0,0,0); out_lay.setSpacing(4)
        out_lay.addWidget(self._section_label("OUTPUT"))
        self.out = OutputView(); self.out.setFont(self._mono(11))
        out_lay.addWidget(self.out, 1)

        self.splitter.addWidget(ed_panel); self.splitter.addWidget(out_panel)
        self.splitter.setSizes([400, 280])

        # ── Action row ────────────────────────────────────────────────────
        actions_wrap = QWidget()
        self._flow = FlowLayout(actions_wrap, margin=0, h_spacing=6, v_spacing=6)

        self.btn_run  = QPushButton("Run")
        self.btn_run.setObjectName("primary")
        self.btn_run.setCursor(_CURSOR_PT)
        self.btn_run.setToolTip("Run the script  (Ctrl+Enter)")

        self.btn_dry = QPushButton("Dry Run")
        self.btn_dry.setObjectName("secondary")
        self.btn_dry.setCursor(_CURSOR_PT)
        self.btn_dry.setToolTip("Plan + diff, no writes  (Ctrl+Shift+Enter)")

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setCursor(_CURSOR_PT)
        self.btn_cancel.setToolTip("Cancel the running script")
        self.btn_cancel.setEnabled(False)

        self.btn_copy_result = QPushButton("Copy PSResult")
        self.btn_copy_result.setObjectName("secondary")
        self.btn_copy_result.setCursor(_CURSOR_PT)
        self.btn_copy_result.setToolTip("Copy the last completed PSRESULT for an AI agent")
        self.btn_copy_result.setEnabled(False)

        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setObjectName("secondary")
        self.btn_undo.setCursor(_CURSOR_PT)
        self.btn_undo.setToolTip("Undo the last run")

        self.btn_load = QPushButton("Load"); self.btn_load.setObjectName("secondary")
        self.btn_load.setCursor(_CURSOR_PT)
        self.btn_save = QPushButton("Save"); self.btn_save.setObjectName("secondary")
        self.btn_save.setCursor(_CURSOR_PT)
        self.btn_test = QPushButton("Test"); self.btn_test.setObjectName("secondary")
        self.btn_test.setCursor(_CURSOR_PT); self.btn_test.setToolTip("Test notifications")
        self.btn_clr  = QPushButton("Clear"); self.btn_clr.setObjectName("secondary")
        self.btn_clr.setCursor(_CURSOR_PT)

        for b in (self.btn_run, self.btn_dry, self.btn_cancel, self.btn_copy_result, self.btn_undo,
                  self.btn_load, self.btn_save, self.btn_test, self.btn_clr):
            self._flow.addWidget(b)
        cl.addWidget(actions_wrap)

        self.status = QLabel("Ready.")
        self.status.setObjectName("status")
        sl = QHBoxLayout(); sl.setContentsMargins(18, 0, 14, 10)
        sl.addWidget(self.status); sl.addStretch(1)
        cl.addLayout(sl)
        root.addWidget(content, 1)

        # Wiring
        self.btn_run.clicked.connect(lambda: self._go(False))
        self.btn_dry.clicked.connect(lambda: self._go(True))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_copy_result.clicked.connect(self._copy_psresult)
        self.btn_undo.clicked.connect(self._undo)
        self.btn_load.clicked.connect(self._load)
        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test_toast)
        self.btn_clr.clicked.connect(self._clear)

        self.btn_run.setShortcut(QKeySequence("Ctrl+Return"))
        self.btn_dry.setShortcut(QKeySequence("Ctrl+Shift+Return"))

        self._esc = QShortcut(QKeySequence(_KEY_ESC), self)
        self._esc.activated.connect(self._clear)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            self._tray.setIcon(make_tray_icon())
            self._tray.setToolTip(f"{APP_NAME} {APP_VERSION}")
            self._tray.show()

        QApplication.clipboard().dataChanged.connect(self._clip_changed)

        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(300)
        self._lint_timer.timeout.connect(self._lint)

        if ("--native-host" in sys.argv or
                any(a.startswith("chrome-extension://") for a in sys.argv[1:])):
            self._native = NativeBridge()
            self._native.message.connect(self._handle_native_message)
            self._native.start()
            self.status.setText("Native bridge connected.")

    # ── helpers ───────────────────────────────────────────────────────────
    def _section_label(self, text):
        lbl = QLabel(text); lbl.setObjectName("sectionLabel"); return lbl

    def _mono(self, size):
        f = QFont("JetBrains Mono", size)
        f.setStyleHint(QFont.StyleHint.Monospace if _QT6 else QFont.Monospace)
        f.setFamilies(["JetBrains Mono", "Cascadia Code", "Consolas", "Menlo", "Monospace"])
        return f

    def _toggle_top(self, on):
        flags = self.windowFlags()
        self.setWindowFlags(flags | _KEEP_ON_TOP if on else flags & ~_KEEP_ON_TOP)
        self.show()

    def _handle_native_message(self, msg):
        if not isinstance(msg, dict):
            return
        typ = msg.get("type")
        if typ == "hello":
            if self._native:
                self._native.send({"v": 1, "type": "hello", "protocol": "PSEDIT/1",
                                   "app": APP_NAME, "version": APP_VERSION, "ready": True})
                self._native.send({"v": 1, "type": "capabilities", "protocol": "PSEDIT/1",
                                   "app": APP_NAME, "version": APP_VERSION,
                                   "operations": ["read_file", "patch_file", "search_files", "list_directory", "run", "wait", "get_job_status", "get_job_output", "cancel", "get_artifact", "ask_user"],
                                   "limits": {"max_file_read_bytes": MAX_FILE_BYTES, "max_runtime_seconds": MAX_RUN_SECONDS, "max_parallel_jobs": 4},
                                   "policy": {"admin": "approval_required", "git_push": "approval_required", "file_delete": "approval_required"},
                                   "ready": True})
            return
        if typ == "ping":
            if self._native:
                self._native.send({"v": 1, "type": "pong", "protocol": "PSEDIT/1",
                                   "version": APP_VERSION})
            return
        if typ == "execute":
            request_id = str(msg.get("request_id") or uuid.uuid4().hex)
            session_id = str(msg.get("session_id") or uuid.uuid4().hex)
            psl = str(msg.get("psl") or msg.get("payload") or "")
            if not psl.strip():
                self._native_reply({"v": 1, "type": "rejected", "request_id": request_id,
                                    "session_id": session_id, "reason": "empty_psl"})
                return
            item = {"request_id": request_id, "session_id": session_id, "psl": psl,
                    "received_at": time.time()}
            self._native_queue.append(item)
            self._native_reply({"v": 1, "type": "accepted", "request_id": request_id,
                                "session_id": session_id, "queued": len(self._native_queue) - 1})
            self._start_next_native()
            return
        if typ == "cancel":
            request_id = str(msg.get("request_id") or "")
            if self._native_current and self._native_current["request_id"] == request_id:
                self._cancel()
                self._native_reply({"v": 1, "type": "cancel_requested", "request_id": request_id})
                return
            before = len(self._native_queue)
            self._native_queue[:] = [x for x in self._native_queue if x["request_id"] != request_id]
            self._native_reply({"v": 1, "type": "cancelled", "request_id": request_id,
                                "queued_removed": before - len(self._native_queue)})

    def _native_reply(self, payload):
        if self._native:
            try:
                self._native.send(payload)
            except Exception:
                pass

    def _start_next_native(self):
        if self._native_current is not None or not self._native_queue:
            return
        item = self._native_queue.pop(0)
        script, errs = parse_script(item["psl"])
        if not script.session_id:
            script.session_id = item["session_id"]
        script.request_id = item["request_id"]
        if errs:
            self._native_reply({"v": 1, "type": "result", "request_id": item["request_id"],
                                "session_id": item["session_id"], "status": "syntax_error",
                                "errors": errs})
            QTimer.singleShot(0, self._start_next_native)
            return
        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)
                 + len(script.run_blocks) + len(script.tree_blocks)
                 + len(script.notify_blocks) + len(script.update_blocks))
        if total == 0:
            self._native_reply({"v": 1, "type": "result", "request_id": item["request_id"],
                                "session_id": item["session_id"], "status": "rejected",
                                "reason": "no_blocks"})
            QTimer.singleShot(0, self._start_next_native)
            return
        if script.has_simultaneous():
            non_run = (len(script.blocks) + len(script.copy_blocks) +
                       len(script.find_blocks) + len(script.tree_blocks))
            non_sim_runs = [r for r in script.run_blocks if r.mode != "simultaneous"]
            if non_run or non_sim_runs or not script.run_blocks:
                self._native_reply({"v": 1, "type": "result", "request_id": item["request_id"],
                                    "session_id": item["session_id"], "status": "rejected",
                                    "reason": "invalid_simultaneous_batch"})
                QTimer.singleShot(0, self._start_next_native)
                return
        self._native_current = item
        self._native_current["script"] = script
        self._native_current["plan"] = make_psplan(script, item["request_id"], item["session_id"])
        self.editor.setPlainText(item["psl"])
        self.out.clear()
        self.status.setText(f"Native job {item['request_id'][:8]}…")
        self._go(False)

    def _finish_native(self, status, extra=None):
        item = self._native_current
        if item is None:
            return
        payload = {"v": 1, "type": "result", "protocol": "PSEDIT/1",
                   "request_id": item["request_id"], "session_id": item["session_id"],
                   "status": status, "plan": item.get("plan")}
        if extra:
            payload.update(extra)
        self._native_reply(payload)
        self._native_current = None
        QTimer.singleShot(0, self._start_next_native)

    def _copy_psresult(self):
        if not self._last_psresult:
            self.status.setText("No PSResult available.")
            return
        QApplication.clipboard().setText(self._last_psresult)
        self._last_clip = self._last_psresult
        self.status.setText("PSResult copied.")
        self.btn_copy_result.setText("Copied")
        QTimer.singleShot(1200, lambda: self.btn_copy_result.setText("Copy PSResult"))

    def _copy_prompt(self):
        QApplication.clipboard().setText(PROMPT_TEXT)
        self.btn_copy_prompt.setText("Copied")
        QTimer.singleShot(1400, lambda: self.btn_copy_prompt.setText("Copy Prompt"))

    def _clear(self):
        self.editor.clear(); self.out.clear(); self.status.setText("Cleared.")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PSL script", "", "PSL (*.psl *.txt);;All (*)")
        if not path: return
        try:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))
            self.status.setText(f"Loaded {path}")
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PSL script", "script.psl", "PSL (*.psl);;All (*)")
        if not path: return
        try:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
            self.status.setText(f"Saved {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_editor_changed(self): self._lint_timer.start()

    def _lint(self):
        text = self.editor.toPlainText()
        if not text.strip(): return
        script, errs = parse_script(text)
        n = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)
             + len(script.run_blocks) + len(script.tree_blocks)
             + len(script.notify_blocks) + len(script.update_blocks))
        if errs:
            self.status.setText(f"⚠ {len(errs)} syntax error(s)")
        elif n == 0:
            self.status.setText("Ready.")
        else:
            bits = []
            if script.blocks:      bits.append(f"{len(script.blocks)} edit")
            if script.copy_blocks: bits.append(f"{len(script.copy_blocks)} copy")
            if script.find_blocks: bits.append(f"{len(script.find_blocks)} find")
            if script.run_blocks:
                concurrent_n = sum(r.mode == "concurrent" for r in script.run_blocks)
                simultaneous_n = sum(r.mode == "simultaneous" for r in script.run_blocks)
                bits.append(f"{len(script.run_blocks)} run")
                if simultaneous_n: bits.append(f"{simultaneous_n} simultaneous")
                if concurrent_n: bits.append(f"{concurrent_n} concurrent")
            if script.tree_blocks: bits.append(f"{len(script.tree_blocks)} tree")
            extra = "  • admin" if script.has_admin() else ""
            self.status.setText("✓ " + " · ".join(bits) + extra)

    def _test_toast(self):
        ok, method = send_toast("PSEdit test", "If you can see this, toasts work.",
                                parent_widget=self, on_click=lambda: None)
        if ok:
            self._append([("ok", f"Toast delivered via {method}")])
            self.status.setText(f"OK via {method}")
        else:
            self._append([("err", "All toast methods failed:"),
                          ("err", f"   {toast_error_summary()}"), ("blank", "")])
            self.status.setText("All toast methods failed.")

    # ── Clipboard: silent takeover, auto-run does what you copied ─────────
    def _clip_changed(self):
        if self.worker is not None and self.worker.isRunning():
            return
        txt = QApplication.clipboard().text()
        if not txt or txt == self._last_clip:
            return
        self._last_clip = txt

        payload = extract_psl_payload(txt)
        if not payload:
            return

        self.editor.setPlainText(payload)
        self.out.clear()
        self.status.setText("Script loaded — Ctrl+Enter to run.")
        self._bring_to_front()
        send_toast("PSEdit", "Script detected — Ctrl+Enter to run.",
                   parent_widget=self, on_click=self._bring_to_front)

        if self.cb_autorun.isChecked():
            QTimer.singleShot(120, lambda: self._go(False))

    def _bring_to_front(self):
        try:
            st = self.windowState()
            st &= ~_WIN_MIN; st |= _WIN_ACT
            self.setWindowState(st)
            if not self.isVisible(): self.show()
            self.raise_(); self.activateWindow()
            QTimer.singleShot(60, self._bring_2)
        except Exception:
            pass

    def _bring_2(self):
        try: self.raise_(); self.activateWindow(); self.editor.setFocus()
        except Exception: pass

    def _undo(self):
        if not self._last_undo:
            self._append([("warn", "Nothing to undo.")]); return
        log = apply_undo(self._last_undo)
        self._last_undo = []
        self._append(log)
        self.status.setText("Undone.")
        self._unflash_undo()

    def _flash_undo(self):
        self.btn_undo.setObjectName("undoHot")
        self.btn_undo.style().unpolish(self.btn_undo)
        self.btn_undo.style().polish(self.btn_undo)
        self.btn_undo.setToolTip("Undo the last run  (files touched)")
        QTimer.singleShot(4000, self._unflash_undo)

    def _unflash_undo(self):
        self.btn_undo.setObjectName("secondary")
        self.btn_undo.style().unpolish(self.btn_undo)
        self.btn_undo.style().polish(self.btn_undo)
        self.btn_undo.setToolTip("Undo the last run")

    def _cancel(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.status.setText("Cancelling…")

    def _on_stream(self, payload):
        kind, text = payload
        self._append([(kind, text)])

    def _on_progress(self, i, total, label):
        self.status.setText(f"Running {i}/{total}: {label}")

    def _on_copy_request(self, payload, ev):
        try:
            QApplication.clipboard().setText(payload)
            self._last_clip = payload
        finally:
            ev.set()

    def _go(self, dry):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Run in progress."); return

        script, errs = parse_script(self.editor.toPlainText())
        if errs:
            self.out.clear()
            self._banner_msg("Syntax errors", f"{len(errs)} problem(s)", "#F87171")
            self._append([("err", f"   ✗ {e}") for e in errs] + [("blank", "")])

        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)
                 + len(script.run_blocks) + len(script.tree_blocks)
                 + len(script.notify_blocks) + len(script.update_blocks))
        if total == 0:
            if not errs:
                self.out.clear()
                self._banner_msg("Nothing to run", "No blocks found.", "#FBBF24")
            self.status.setText("Nothing to run."); return

        if script.has_simultaneous():
            non_run = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks) + len(script.tree_blocks))
            non_sim_runs = [r for r in script.run_blocks if r.mode != "simultaneous"]
            if non_run or non_sim_runs or not script.run_blocks:
                self.out.clear()
                self._banner_msg("Invalid simultaneous batch",
                                 "Simultaneous mode currently accepts only simultaneous PSRun/PSRunAdmin blocks.",
                                 "#F87171")
                self.status.setText("Simultaneous batch rejected.")
                return
            if dry:
                self.out.clear()
                self._banner_msg("DRY RUN", f"{len(script.run_blocks)} simultaneous command(s)", "#75BEFF")
                for i, r in enumerate(script.run_blocks, 1):
                    self._append([("info", f"[{i}/{len(script.run_blocks)}] would start: {r.cmd.split('\n', 1)[0]}")])
                self._append([("blank", "")])
                self.status.setText("Dry run complete.")
                return
            self._start_simultaneous(script.run_blocks, script.session_id)
            return

        self.out.clear()
        self._busy(True)
        self.btn_cancel.setEnabled(True)
        label = "DRY RUN" if dry else "RUN"
        self._banner_msg(label, f"{total} block(s)",
                         "#75BEFF" if dry else "#4FC1FF")

        self.worker = Worker(
            script, dry,
            True if self.cb_bak.isChecked()  else None,
            True if self.cb_push.isChecked() else None,
            safe_mode=self.cb_safe.isChecked(),
        )
        self.worker.done.connect(self._done)
        self.worker.stream.connect(self._on_stream)
        self.worker.copy_request.connect(self._on_copy_request)
        self.worker.progress.connect(self._on_progress)
        self.worker.start()

    def _start_simultaneous(self, run_blocks, session_id):
        self.out.clear()
        self._busy(True)
        self.btn_cancel.setEnabled(False)
        self._sim_results = []
        self._sim_expected = len(run_blocks)
        self._sim_batch_id = uuid.uuid4().hex
        self._sim_windows = []
        self._banner_msg("SIMULTANEOUS", f"{self._sim_expected} independent run(s)", "#4FC1FF")
        self._append([("info", "Each command has its own PSEdit run window. The aggregate PSRESULT is available only after every job finishes."), ("blank", "")])
        for i, rb in enumerate(run_blocks, 1):
            rb.session_id = session_id
            w = RunJobWindow(rb, i, self._sim_expected, self.cb_safe.isChecked(), self)
            w.finished_result.connect(self._on_sim_result)
            w.show()
            self._sim_windows.append(w)

    def _on_sim_result(self, payload):
        result, ok = payload
        self._sim_results.append(result)
        self._append([("ok" if ok else "warn",
                       f"SIM {len(self._sim_results)}/{self._sim_expected} finished — {result.get('status')} — {result.get('command', '')[:70]}"), ("blank", "")])
        if len(self._sim_results) < self._sim_expected:
            self.status.setText(f"Waiting for simultaneous results: {len(self._sim_results)}/{self._sim_expected}")
            return
        self._sim_results.sort(key=lambda r: r.get("_order", 0))
        for r in self._sim_results:
            r.pop("_order", None)
        self._last_psresult = make_psresults(self._sim_results, self._sim_batch_id)
        self.btn_copy_result.setEnabled(True)
        if self.cb_return.isChecked():
            QApplication.clipboard().setText(self._last_psresult)
            self._last_clip = self._last_psresult
        all_ok = all(r.get("status") == "success" for r in self._sim_results)
        self._append([("ok" if all_ok else "warn", "ALL simultaneous jobs finished."), ("blank", "")])
        self._busy(False)
        if all_ok:
            self.status.setText(f"All {self._sim_expected} simultaneous jobs finished — PSResult ready.")
        else:
            self.status.setText(f"{sum(r.get('status') == 'success' for r in self._sim_results)}/{self._sim_expected} simultaneous jobs succeeded — PSResult ready.")
        send_toast("PSEdit", f"All {self._sim_expected} simultaneous runs finished. PSResult ready.", parent_widget=self)
        if self._native_current is not None:
            all_ok = all(r.get("status") == "success" for r in self._sim_results)
            self._finish_native("success" if all_ok else "failed", {
                "plan": self._native_current.get("plan") if self._native_current else None,
                "file_reads": native_file_reads(self._native_current.get("script")) if self._native_current and self._native_current.get("script") else [],
                "run_results": self._sim_results,
                "psresult": self._last_psresult,
            })

    def _done(self, payload):
        ok, undo, log, run_results = payload
        self._append(log)
        self.out.moveCursor(_END)
        self.out.insertHtml('<div style="color:#1F1F24;">' + "═" * 46 + "</div>")
        if undo:
            self._last_undo = undo
            self._flash_undo()
        if run_results:
            self._last_psresult = (make_psresult(run_results[0]) if len(run_results) == 1
                                   else make_psresults(run_results))
            self.btn_copy_result.setEnabled(True)
            if self.cb_return.isChecked():
                QApplication.clipboard().setText(self._last_psresult)
                self._last_clip = self._last_psresult
        self._busy(False)
        self.btn_cancel.setEnabled(False)
        if ok:
            n = len(undo) if undo else 0
            self.status.setText(
                f"Done. {n} file(s) touched — Undo available." if n else "Done.")
            send_toast("PSEdit", f"{n} file(s) edited" if n else "Done",
                       parent_widget=self)
        else:
            self.status.setText("Aborted.")
        if self._native_current is not None:
            log_text = "\n".join(text for _kind, text in log)
            self._finish_native("success" if ok else "failed", {
                "plan": self._native_current.get("plan") if self._native_current else None,
                "file_reads": native_file_reads(self._native_current.get("script")) if self._native_current and self._native_current.get("script") else [],
                "run_results": run_results,
                "undo_count": len(undo),
                "log": log_text,
                "psresult": self._last_psresult,
            })

    def _append(self, entries):
        self.out.moveCursor(_END)
        self.out.insertHtml(to_html(entries))
        sb = self.out.verticalScrollBar(); sb.setValue(sb.maximum())

    def _banner_msg(self, title, sub, color):
        self.out.moveCursor(_END)
        self.out.insertHtml(
            f'<div style="color:{color}; font-weight:bold; font-size:11pt;'
            f' margin-top:6px;">{html.escape(title)}</div>'
            f'<div style="color:{color}; margin-bottom:2px; font-size:9pt; opacity:0.8;">'
            f'{html.escape(sub)}</div>')

    def _busy(self, b):
        for w in (self.btn_run, self.btn_dry, self.btn_copy_result, self.btn_undo, self.btn_load,
                  self.btn_save, self.btn_test, self.btn_clr):
            w.setEnabled(not b)

    def closeEvent(self, e):
        if self._tray is not None:
            try: self._tray.hide()
            except Exception: pass
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        if self._native is not None:
            self._native.stop()
        super().closeEvent(e)

# --- Headless protocol self-test --------------------------------------------
def run_headless_self_test():
    if "--self-test" not in sys.argv:
        return False
    root = Path(tempfile.mkdtemp(prefix="psedit_v11_test_"))
    try:
        # Existing-file optimistic concurrency protection.
        target = root / "sample.txt"
        target.write_text("alpha\nbeta\n", encoding="utf-8")
        psl = ("__PSEDIT_BEGIN__ session=test_session\n"
               f"psedit::\n\"{target}\"\npsfrom::\nbeta\npsto::\nBETA\n__finish__")
        script, errs = parse_script(psl)
        assert not errs, errs
        plan, fatal, _ = build_plan(script)
        assert fatal == 0 and plan and plan[0].expected_sha256
        expected = plan[0].expected_sha256
        target.write_text("alpha\nbeta-changed\n", encoding="utf-8")
        ok, _, log, _ = execute_plan(plan, script, False, False, False, None, lambda _: None, threading.Event())
        assert not ok
        assert any("stale precondition" in text for _, text in log)
        assert sha256_bytes(target.read_bytes()) != expected

        # New-file creation must not attempt a precondition read.
        created = root / "nested" / "created.txt"
        psl_create = ("__PSEDIT_BEGIN__ session=test_create\n"
                      f"psedit::\n\"{created}\"\npsfrom::\npsto::\nhello\n__finish__")
        script, errs = parse_script(psl_create)
        assert not errs, errs
        plan, fatal, _ = build_plan(script)
        assert fatal == 0 and len(plan) == 1 and plan[0].is_new_file
        ok, _, log, _ = execute_plan(plan, script, False, False, False, None, lambda _: None, threading.Event())
        assert ok and created.read_text(encoding="utf-8") == "hello"

        # Empty new files must also be created rather than treated as no-op.
        empty = root / "nested" / "empty.txt"
        psl_empty = ("__PSEDIT_BEGIN__ session=test_empty\n"
                     f"psedit::\n\"{empty}\"\npsfrom::\npsto::\n__finish__")
        script, errs = parse_script(psl_empty)
        assert not errs, errs
        plan, fatal, _ = build_plan(script)
        assert fatal == 0 and len(plan) == 1 and plan[0].is_new_file
        ok, _, log, _ = execute_plan(plan, script, False, False, False, None, lambda _: None, threading.Event())
        assert ok and empty.exists() and empty.read_bytes() == b""

        print(json.dumps({
            "status": "ok",
            "tests": [
                "typed_plan",
                "hash_precondition",
                "new_file_creation",
                "empty_file_creation",
                "nested_directory_creation"
            ]
        }))
        return True
    finally:
        shutil.rmtree(root, ignore_errors=True)

# --- Entry point ------------------------------------------------------------
def main():
    if run_headless_self_test():
        return
    native_mode = "--native-host" in sys.argv or any(
        a.startswith("chrome-extension://") for a in sys.argv[1:])
    if native_mode and any(a.startswith("chrome-extension://") for a in sys.argv[1:]):
        origin = next(a for a in sys.argv[1:] if a.startswith("chrome-extension://"))
        expected = f"chrome-extension://{NATIVE_EXTENSION_ID}/"
        if origin != expected:
            return 2
    if native_mode and sys.platform.startswith("win"):
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "PSEDIT.ico" if getattr(sys, "_MEIPASS", "") else None,
        Path(sys.argv[0]).resolve().with_name("PSEDIT.ico"),
        Path(__file__).resolve().with_name("PSEDIT.ico"),
    ]
    icon_path = next((p for p in icon_candidates if p and p.exists()), None)
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    w = NativeDashboard() if native_mode else Main()
    w.show()
    sys.exit(app.exec() if _QT6 else app.exec_())

if __name__ == "__main__":
    main()