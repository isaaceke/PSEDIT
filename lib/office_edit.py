"""office_edit.py — apply edits to xlsx/docx via COM, validate, report."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from psedit_office import edit_xlsx_com, edit_docx_com, validate_office


def _smart_value(v):
    if v is None:
        return None
    s = str(v)
    if s == "":
        return None
    try:
        if "." not in s and "," not in s:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s.replace(",", "."))
    except ValueError:
        pass
    return s


def main():
    if len(sys.argv) < 3:
        print("usage: office_edit.py <file> <json> [--validate]")
        return 2
    src = sys.argv[1]
    edits_file = sys.argv[2]
    do_validate = "--validate" in sys.argv[3:]

    if not Path(src).exists():
        print("error: source not found:", src)
        return 1
    with open(edits_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    kind = payload.get("kind", "xlsx")
    edits = payload.get("edits", [])

    if kind == "xlsx":
        clean = []
        for e in edits:
            clean.append({
                "sheet": e["sheet"],
                "cell": e["cell"],
                "value": _smart_value(e.get("value")),
            })
        print("xlsx edits:", len(clean))
        result = edit_xlsx_com(src, clean)
    elif kind == "docx":
        clean = []
        for e in edits:
            clean.append({
                "find": e.get("find", ""),
                "replace": e.get("replace", ""),
                "match_case": bool(e.get("match_case", False)),
            })
        print("docx edits:", len(clean))
        result = edit_docx_com(src, clean)
    else:
        print("unknown kind:", kind)
        return 1

    print("applied:", result.get("applied", 0))
    for err in result.get("errors", []):
        print("error:", err)

    if do_validate:
        v = validate_office(src)
        print("validate:", "ok" if v.get("ok") else v.get("error"))
        if not v.get("ok"):
            return 1

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())