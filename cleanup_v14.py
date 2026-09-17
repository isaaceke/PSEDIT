"""One-shot cleanup: sort old files into _old and _misc, archive exes."""
import os
import shutil
from pathlib import Path

ROOT = Path(r"C:\Users\HP\Downloads\PSEDIT")
_old  = ROOT / "_old"
_misc = ROOT / "_misc"
dbak  = ROOT / "dist" / ".bak"

for d in (_old, _misc, dbak):
    d.mkdir(parents=True, exist_ok=True)

to_old = [
    "build-v12.ps1",
    "dep_check.py",
    "env_check.py",
    "fix_indent.py",
    "make_report.py",
    "read_propellers.bat",
    "patch_a.py", "patch_b.py", "patch_c.py", "patch_d.py",
    "patch_e.py", "patch_office_markers.py", "patch_prompt.py",
    "patch_selectable.py", "patch_visible_capture.py", "patch_worker.py",
    "PseDIT.spec", "PseDIT_v13.spec",
    "PseDIT_v12.py", "PseDIT_v13.py",
]

to_misc = [
    "dep_result.txt", "env_result.txt", "gate_test.txt",
    "input_dump.txt", "lib_selftest.txt", "pip_out.txt",
    "propellers_read.txt", "summary_test.txt", "summary_test_2.txt",
    "v12_test.txt",
    "office_test.xlsx", "office_test_edit.json", "docx_test.docx",
    "PROPELLER_REPORT.docx",
    "build_report.py",
]

moved_old = moved_misc = 0
for name in to_old:
    src = ROOT / name
    if src.exists():
        shutil.move(str(src), str(_old / name))
        moved_old += 1
for name in to_misc:
    src = ROOT / name
    if src.exists():
        shutil.move(str(src), str(_misc / name))
        moved_misc += 1

# Move old lib file
lib_old = ROOT / "lib" / "psedit_office.py.old"
if lib_old.exists():
    shutil.move(str(lib_old), str(_old / "psedit_office.py.old"))
    moved_old += 1

# Archive current exe, delete all other versioned exes
current = ROOT / "dist" / "PseDIT.exe"
archive = dbak / "PseDIT_v14.exe"
if current.exists():
    shutil.copy2(str(current), str(archive))

removed_exes = 0
for f in (ROOT / "dist").glob("PseDIT_v*.exe"):
    try:
        f.unlink()
        removed_exes += 1
    except Exception as e:
        print("could not remove", f.name, e)

print("moved to _old:", moved_old)
print("moved to _misc:", moved_misc)
print("exes removed:", removed_exes)
print("archive:", archive.name, "->", archive.stat().st_size if archive.exists() else 0, "bytes")