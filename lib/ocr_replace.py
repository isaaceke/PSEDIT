"""
ocr_replace.py — find images containing a keyword in a Word doc, replace them.

Usage:
    py -3 ocr_replace.py <docx> <keyword> <replacement.png> [--case-sensitive] [--dump]

--dump     report matches only, do not modify
--case-sensitive  exact case matching (default: case-insensitive)

OCR uses Windows.Media.Ocr via PowerShell. No third-party libraries.
"""
import sys
import json
import base64
import subprocess
import tempfile
from pathlib import Path

try:
    import win32com.client
    import pythoncom
except ImportError:
    print("error: pywin32 not installed")
    sys.exit(2)


OCR_PS = r'''
param([string]$ImagePath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
[void][Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) {
    Write-Output '{"error":"no OCR language pack available"}'
    exit 1
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$text = ($result.Text)
Write-Output (ConvertTo-Json @{ text = $text } -Compress)
'''


def ocr_image(image_path):
    tmp_ps = Path(tempfile.gettempdir()) / ("psedit_ocr_" + next(tempfile._get_candidate_names()) + ".ps1")
    tmp_ps.write_text(OCR_PS, encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(tmp_ps), "-ImagePath", str(image_path)],
            capture_output=True, text=True, timeout=60, creationflags=flags)
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout or "ocr failed").strip()}
        try:
            return json.loads(r.stdout.strip().split("\n")[-1])
        except Exception as e:
            return {"error": "json parse: " + str(e), "raw": r.stdout[:200]}
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            tmp_ps.unlink(missing_ok=True)
        except Exception:
            pass


def norm(s):
    return "".join(ch.lower() for ch in (s or "") if ch.isalnum())


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    docx = Path(sys.argv[1])
    keyword = sys.argv[2]
    replacement = Path(sys.argv[3])
    dump = "--dump" in sys.argv[4:]
    case_sensitive = "--case-sensitive" in sys.argv[4:]

    if not docx.exists():
        print("error: docx not found: " + str(docx))
        return 1
    if not replacement.exists():
        print("error: replacement image not found: " + str(replacement))
        return 1

    pythoncom.CoInitialize()
    word = None
    doc = None
    matched = []
    scanned = 0
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx.resolve()), ReadOnly=False)

        tmpdir = Path(tempfile.gettempdir())
        for si in range(1, doc.InlineShapes.Count + 1):
            scanned += 1
            shape = doc.InlineShapes(si)
            tmp_png = tmpdir / ("psedit_img_" + str(si) + ".png")
            try:
                shape.Range.Select()
                word.Selection.CopyAsPicture()
                # Save via XML trick: get the image bytes directly is not
                # exposed. Use ExportAsFixedFormat is too heavy. Instead use
                # the Range.Copy + SaveAsPicture path:
                if doc.InlineShapes(si).Type == 3:  # wdInlineShapePicture
                    doc.InlineShapes(si).Range.Copy()
                    # fall through: we save via the clipboard in a moment
            except Exception as e:
                print("shape %d: extract failed: %s" % (si, e))
                continue

            # Use PowerShell + System.Windows.Forms.Clipboard to save the
            # image just copied:
            save_ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$img = [System.Windows.Forms.Clipboard]::GetImage();"
                "if ($img) { $img.Save('" + str(tmp_png).replace("'", "''") + "', "
                "[System.Drawing.Imaging.ImageFormat]::Png) }"
            )
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command", save_ps],
                    capture_output=True, text=True, timeout=20,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:
                print("shape %d: save failed: %s" % (si, e))
                continue

            if not tmp_png.exists():
                print("shape %d: no png produced" % si)
                continue

            ocr = ocr_image(tmp_png)
            if "text" not in ocr:
                print("shape %d: ocr error: %s" % (si, ocr.get("error", "unknown")))
                continue
            text = ocr["text"]
            haystack = text if case_sensitive else text.lower()
            needle = keyword if case_sensitive else keyword.lower()
            hit = needle in haystack
            print("shape %d: %r -> hit=%s" % (si, text[:80], hit))
            if hit:
                matched.append(si)

        print()
        print("scanned: %d" % scanned)
        print("matched: %d" % len(matched))
        print("indices: %s" % matched)

        if dump or not matched:
            return 0

        # Replace each matched shape's image
        for si in matched:
            try:
                shape = doc.InlineShapes(si)
                shape.Range.Select()
                # Delete old picture, insert new at same anchor
                shape.Delete()
                word.Selection.InlineShapes.AddPicture(str(replacement.resolve()))
            except Exception as e:
                print("replace %d failed: %s" % (si, e))

        doc.Save()
        doc.Close(SaveChanges=False)
        doc = None
        print("saved: " + str(docx))
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