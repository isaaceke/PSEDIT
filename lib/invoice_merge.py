"""
invoice_merge.py — merge Excel rows into a Word invoice template.

Usage:
    py -3 invoice_merge.py <template.docx> <data.xlsx> <output.docx> [--sheet NAME] [--dump]

--dump     print structure only, write nothing
--sheet    worksheet name (default: active sheet)

Uses Word COM for the docx side (row duplication is a native Word op)
and openpyxl for reading the data. Nothing else.
"""
import sys
import json
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("error: openpyxl not installed")
    sys.exit(2)

try:
    import win32com.client
    import pythoncom
except ImportError:
    print("error: pywin32 not installed")
    sys.exit(2)


WD_ROW_INSERT_ABOVE = 1  # relative to a row object


def norm(s):
    return "".join(ch.lower() for ch in (s or "") if ch.isalnum())


def dump_docx_table(doc):
    out = []
    out.append("paragraphs:")
    for i, p in enumerate(doc.Paragraphs):
        t = (p.Range.Text or "").rstrip("\r\x07")
        if t.strip():
            out.append("  [%d] %r" % (i, t[:80]))
    out.append("tables: " + str(doc.Tables.Count))
    for ti in range(1, doc.Tables.Count + 1):
        tbl = doc.Tables(ti)
        rows = tbl.Rows.Count
        cols = tbl.Columns.Count
        out.append("  table %d: %d x %d" % (ti, rows, cols))
        for r in range(1, min(rows, 6) + 1):
            row_vals = []
            for c in range(1, cols + 1):
                try:
                    cell = tbl.Cell(r, c)
                    txt = cell.Range.Text or ""
                    row_vals.append(txt.rstrip("\r\x07")[:30])
                except Exception as e:
                    row_vals.append("<%s>" % e)
            out.append("    r%d: %s" % (r, " | ".join(row_vals)))
        if rows > 6:
            out.append("    ... (%d more rows)" % (rows - 6))
    return "\n".join(out)


def read_excel(path, sheet_name=None):
    wb = openpyxl.load_workbook(str(path), data_only=True, keep_links=False, keep_vba=False)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = ["" if v is None else str(v) for v in rows[0]]
    data = []
    for r in rows[1:]:
        if all(v is None for v in r):
            continue
        data.append(["" if v is None else v for v in r])
    return headers, data


def find_header_row(table):
    for r in range(1, min(4, table.Rows.Count) + 1):
        hits = 0
        for c in range(1, table.Columns.Count + 1):
            try:
                txt = (table.Cell(r, c).Range.Text or "").rstrip("\r\x07")
                if txt.strip():
                    hits += 1
            except Exception:
                pass
        if hits >= 2:
            return r
    return 1


def map_headers(docx_headers, xlsx_headers):
    """Return list of (xlsx_col_index, docx_col_index) pairs."""
    pairs = []
    used = set()
    for xi, xh in enumerate(xlsx_headers):
        n = norm(xh)
        if not n:
            continue
        for di, dh in enumerate(docx_headers):
            if di in used:
                continue
            if norm(dh) == n:
                pairs.append((xi, di))
                used.add(di)
                break
    return pairs


def find_template_row(table, header_row, docx_headers):
    """First data row after header."""
    return header_row + 1


def clear_data_rows(table, from_row):
    """Delete all rows from from_row to end. Word rows shift up, so delete
    from the end."""
    while table.Rows.Count >= from_row:
        table.Rows(table.Rows.Count).Delete()


def fill_row(table, row_idx, values, template_row):
    """Set cell text. Formatting is preserved because we replace the range
    text rather than the cell."""
    for ci, v in enumerate(values, start=1):
        try:
            cell = table.Cell(row_idx, ci)
            cell.Range.Text = "" if v is None else str(v)
        except Exception:
            pass


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    template = Path(sys.argv[1])
    datafile = Path(sys.argv[2])
    output = Path(sys.argv[3])
    dump_only = "--dump" in sys.argv[4:]
    sheet = None
    if "--sheet" in sys.argv:
        i = sys.argv.index("--sheet")
        if i + 1 < len(sys.argv):
            sheet = sys.argv[i + 1]

    if not template.exists():
        print("error: template not found: " + str(template))
        return 1
    if not datafile.exists():
        print("error: data not found: " + str(datafile))
        return 1

    xlsx_headers, xlsx_data = read_excel(datafile, sheet)
    print("excel: %d rows, %d cols" % (len(xlsx_data), len(xlsx_headers)))
    print("excel headers: " + " | ".join(xlsx_headers[:12]))

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(template.resolve()), ReadOnly=False)

        print()
        print("=== docx structure ===")
        print(dump_docx_table(doc))

        if dump_only:
            return 0

        if doc.Tables.Count == 0:
            print("error: no tables found")
            return 1

        table = doc.Tables(1)
        header_row = find_header_row(table)
        docx_headers = []
        for c in range(1, table.Columns.Count + 1):
            try:
                txt = (table.Cell(header_row, c).Range.Text or "").rstrip("\r\x07")
            except Exception:
                txt = ""
            docx_headers.append(txt)
        print()
        print("docx header row: " + str(header_row))
        print("docx headers: " + " | ".join(docx_headers))

        pairs = map_headers(docx_headers, xlsx_headers)
        print()
        print("header mapping:")
        for xi, di in pairs:
            print("  xlsx[%d] %r -> docx col %d" % (xi, xlsx_headers[xi], di + 1))
        if not pairs:
            print("error: no headers matched")
            return 1

        template_row = find_template_row(table, header_row, docx_headers)
        clear_data_rows(table, template_row)
        print("cleared rows from %d, now %d rows" % (template_row, table.Rows.Count))

        added = 0
        for row in xlsx_data:
            table.Rows.Add()
            r = table.Rows.Count
            blanks = ["" for _ in docx_headers]
            for xi, di in pairs:
                if xi < len(row):
                    blanks[di] = row[xi]
            fill_row(table, r, blanks, template_row)
            added += 1
        print("added %d data rows" % added)

        doc.SaveAs2(str(output.resolve()))
        doc.Close(SaveChanges=False)
        doc = None
        print("saved: " + str(output))
        return 0
    finally:
        try:
            if doc is not None:
                doc.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    sys.exit(main())