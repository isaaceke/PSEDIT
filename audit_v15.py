from pathlib import Path

v15 = Path(r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py").read_text(encoding="utf-8")
spec = Path(r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.spec").read_text(encoding="utf-8")

print("v15 size:", len(v15))
for line in v15.splitlines():
    if "APP_VERSION" in line and "=" in line:
        print("version:", line.strip())
        break

checks = [
    ("PowerShell runner",    'powershell", "-NoProfile"'),
    ("cmd bat runner",       'cmd", "/c"'),
    ("_notify method",       "def _notify"),
    ("psupdate marker",      "MARK_PSUPDATE"),
    ("psnotify marker",      "MARK_PSNOTIFY"),
    ("psupdate handler",     "def _handle_psupdate"),
    ("psnotify handler",     "def _handle_psnotify"),
    ("eta option",           "eta"),
    ("office errors in PSRESULT", "office_errors"),
]
for label, needle in checks:
    print(f"  {label:<28} {needle in v15}")

print()
print("spec references v15:", "PseDIT_v15.py" in spec)
print("spec name PseDIT:", "name='PseDIT'" in spec)