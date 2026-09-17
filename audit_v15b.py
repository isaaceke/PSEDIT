from pathlib import Path

src = Path(r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py").read_text(encoding="utf-8")

checks = [
    ("1  prompt has no literal backslash-n",  "\\\\n-" not in src and "VERSIONING CONVENTION:" in src),
    ("2  visible runner isolates user cmd",   "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $userScript" in src),
    ("2b visible runner has try/catch",       "$rc = if ($LASTEXITCODE" in src and "} catch {" in src),
    ("4  notify fallback call",               "if not _ok:" in src and "_notify_via_powershell(_title, _body)" in src),
    ("4b notify helper defined",              "def _notify_via_powershell(title, msg):" in src),
    ("5  office written-before-check",        "written.append(step.path)" in src and "if rc == 0:" in src),
    ("6  totals include notify+update",       "len(script.notify_blocks) + len(script.update_blocks)" in src),
    ("7  user script separate file",          "userscript = tmpdir / " in src),
    ("8  no bare & { wrapper",                "& {" + chr(10) + "        step.cmd" not in src),
    ("9  utf-8-sig log read",                 "encoding=\"utf-8-sig\"" in src),
    ("10 office backup aborts",               "backup failed, aborting" in src),
    ("11 no duplicate PSRESULT paragraph",    src.count("PSRESULT is designed for ANY consuming AI") == 1),
]

for label, ok in checks:
    print(("PASS  " if ok else "FAIL  ") + label)

print()
print("source lines:", src.count(chr(10)) + 1)
print("def count:", src.count(chr(10) + "def "))
print("class count:", src.count(chr(10) + "class "))

# shape check for the notify branch
i = src.find('elif step.kind == "notify":')
if i >= 0:
    chunk = src[i:i+800]
    print("notify branch ends with 'elif step.kind'?", "elif step.kind" in chunk[10:])
    print("notify branch has 2 elifs after it?",
          chunk.count("elif step.kind") >= 1)