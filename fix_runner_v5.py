import io
P = r"C:\Users\HP\Downloads\PSEDIT\PseDIT_v15.py"
with io.open(P, "r", encoding="utf-8") as f:
    src = f.read()

NL = chr(10)

old_bak = (
    '                except Exception as _e:' + NL
    + '                    log.append(("warn", "   backup failed: " + str(_e)))'
)
new_bak = (
    '                except Exception as _e:' + NL
    + '                    log.append(("err", "   backup failed, aborting: " + str(_e)))' + NL
    + '                    fatal = True' + NL
    + '                    if script.stop_on_err: break' + NL
    + '                    log.append(("blank", "")); continue'
)

if old_bak in src:
    src = src.replace(old_bak, new_bak, 1)
    print("OK   office backup failure aborts")
else:
    print("MISS office backup anchor")
    raise SystemExit(1)

with io.open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("fix_runner_v5 done")