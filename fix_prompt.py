import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

BS = chr(92)
NL = chr(10)

def sub(old, new, label, required=True):
    global src
    n = src.count(old)
    if n > 0:
        src = src.replace(old, new)
        print("OK   " + label + " (" + str(n) + ")")
        return True
    print("MISS " + label)
    if required:
        print("     head: " + repr(old[:100]))
    return False

# Fix 1 + 11: literal backslash-n and duplicate option text in prompt
old_prompt = (
    "VERSIONING CONVENTION:" + BS + "n- Every edit to an existing file (text, docx, xlsx) automatically saves a"
    + BS + "n  versioned copy to .bak/ next to the original, named <name>_v<N><ext>."
    + BS + "n- Set create.bak {false} to opt out; create.bak {N} controls keep count."
    + BS + "n- Exes and binaries are not backed up; only source and document files."
    + BS + "n" + BS + "nOPTIONS (anywhere, one per line):" + NL
    + "  create.bak    {true|false|N}   # .bak/ folder next to each edited file;"
    + BS + "n                                 # duplicate is renamed to <name>_v<N><ext>;"
    + BS + "n                                 # keep N most recent (default 3); default ON."
    + BS + "n                                 # Setting create.bak {false} disables versioning." + NL
    + "  Git push      {true|false}     # stage + commit + push ONLY files PSEdit touched" + NL
    + "  stop.on.error {true|false}     # default true: abort + rollback on any miss" + NL
    + "                                 # (stop.onerror also accepted \u2014 same option)" + NL
    + "                                 # (stop.onerror also accepted \u2014 same option)"
)
new_prompt = (
    "VERSIONING CONVENTION:" + NL
    + "- Every edit to an existing file (text, docx, xlsx) automatically saves a" + NL
    + "  versioned copy to .bak/ next to the original, named <name>_v<N><ext>." + NL
    + "- Set create.bak {false} to opt out; create.bak {N} controls keep count." + NL
    + "- Exes and binaries are not backed up; only source and document files." + NL
    + NL
    + "OPTIONS (anywhere, one per line):" + NL
    + "  create.bak    {true|false|N}   # .bak/ folder next to each edited file;" + NL
    + "                                 # duplicate is renamed to <name>_v<N><ext>;" + NL
    + "                                 # keep N most recent (default 3); default ON." + NL
    + "                                 # Setting create.bak {false} disables versioning." + NL
    + "  Git push      {true|false}     # stage + commit + push ONLY files PSEdit touched" + NL
    + "  stop.on.error {true|false}     # default true: abort + rollback on any miss" + NL
    + "                                 # (stop.onerror also accepted \u2014 same option)"
)
sub(old_prompt, new_prompt, "prompt backslash-n + duplicate option line")

# Fix 11: 7b/7c duplicated block
old_7bc = (
    "# 7b) Run with a VISIBLE console window:" + NL
    + "#     Opens a real terminal, runs live, auto-closes on exit 0," + NL
    + "#     pauses on failure so the user can read the output." + NL
    + "psrun{visible}::" + NL
    + "<command line>" + NL
    + NL
    + "# 7c) Combine mode and visibility: psrun{concurrent,visible}::" + NL
    + "#     or psrun{simultaneous,visible}::" + NL
    + NL
    + "# 7b) Run with a VISIBLE console window:" + NL
    + "#     Opens a real terminal, runs live, auto-closes on exit 0," + NL
    + "#     pauses on failure so the user can read the output." + NL
    + "psrun{visible}::" + NL
    + "<command line>" + NL
    + NL
    + "# 7c) Combine mode and visibility: psrun{concurrent,visible}::" + NL
    + "#     or psrun{simultaneous,visible}::"
)
new_7bc = (
    "# 7b) Run with a VISIBLE console window:" + NL
    + "#     Opens a real terminal, runs live, auto-closes on exit 0," + NL
    + "#     pauses on failure so the user can read the output." + NL
    + "psrun{visible}::" + NL
    + "<command line>" + NL
    + NL
    + "# 7c) Combine mode and visibility: psrun{concurrent,visible}::" + NL
    + "#     or psrun{simultaneous,visible}::"
)
sub(old_7bc, new_7bc, "prompt 7b/7c duplicate")

# Fix 11: PSRESULT duplicate paragraph
old_psr = (
    "- PSRESULT is designed for ANY consuming AI, not just the one that issued" + NL
    + "  the PSL. It carries status, per-step results, exit codes, and a summary" + NL
    + "  line that can be quoted verbatim." + NL
    + "- PSRESULT is designed for ANY consuming AI, not just the one that issued" + NL
    + "  the PSL. It carries status, per-step results, exit codes, and a summary" + NL
    + "  line that can be quoted verbatim."
)
new_psr = (
    "- PSRESULT is designed for ANY consuming AI, not just the one that issued" + NL
    + "  the PSL. It carries status, per-step results, exit codes, and a summary" + NL
    + "  line that can be quoted verbatim."
)
sub(old_psr, new_psr, "prompt PSRESULT duplicate")

# Fix 6a: totals in Main._go and Main._start_next_native (identical text, 2 occurrences)
old_t1 = (
    "        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)" + NL
    + "                 + len(script.run_blocks) + len(script.tree_blocks))"
)
new_t1 = (
    "        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)" + NL
    + "                 + len(script.run_blocks) + len(script.tree_blocks)" + NL
    + "                 + len(script.notify_blocks) + len(script.update_blocks))"
)
sub(old_t1, new_t1, "totals in Main (2 sites)")

# Fix 6b: NativeDashboard._submit single-line totals
old_t2 = "        total = len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks) + len(script.run_blocks) + len(script.tree_blocks)"
new_t2 = (
    "        total = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)" + NL
    + "                 + len(script.run_blocks) + len(script.tree_blocks)" + NL
    + "                 + len(script.notify_blocks) + len(script.update_blocks))"
)
sub(old_t2, new_t2, "totals in NativeDashboard._submit")

# Fix 6c: _lint totals
old_t3 = (
    "        n = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)" + NL
    + "             + len(script.run_blocks) + len(script.tree_blocks))"
)
new_t3 = (
    "        n = (len(script.blocks) + len(script.copy_blocks) + len(script.find_blocks)" + NL
    + "             + len(script.run_blocks) + len(script.tree_blocks)" + NL
    + "             + len(script.notify_blocks) + len(script.update_blocks))"
)
sub(old_t3, new_t3, "totals in _lint")

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("fix_prompt done")