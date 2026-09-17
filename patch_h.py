import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

START = '''        elif step.kind == "update":'''
END = '''        elif step.kind == "run":'''

i = src.find(START)
j = src.find(END, i)
if i < 0 or j < 0:
    print("FAIL: start", i, "end", j)
    raise SystemExit(1)

new_block = '''        elif step.kind == "update":
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

        elif step.kind == "run":'''

src = src[:i] + new_block + src[j + len(END):]
with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("patch_h done: update block rewritten")