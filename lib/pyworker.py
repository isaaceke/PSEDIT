"""Persistent Python worker for PSEdit.

Reads __RUN__ <path> lines on stdin, executes each file, writes
stdout/stderr to the same streams, then emits a sentinel line:
    __PSEdit_WORKER_DONE__ <exit_code>

Spawned once by PseDIT and kept alive for the life of the process.
"""

import io
import runpy
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr


def _run_one(path):
    out = io.StringIO()
    err = io.StringIO()
    rc = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        code = e.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
    except BaseException:
        err.write(traceback.format_exc())
        rc = 1
    return rc, out.getvalue(), err.getvalue()


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for line in sys.stdin:
        s = line.strip()
        if not s:
            continue
        if s == "__QUIT__":
            return 0
        if not s.startswith("__RUN__ "):
            continue
        target = s[8:].strip()
        rc, o, e = _run_one(target)
        if o:
            sys.stdout.write(o)
            if not o.endswith("\n"):
                sys.stdout.write("\n")
        if e:
            sys.stderr.write(e)
            if not e.endswith("\n"):
                sys.stderr.write("\n")
        sys.stdout.write("__PSEdit_WORKER_DONE__ " + str(rc) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())