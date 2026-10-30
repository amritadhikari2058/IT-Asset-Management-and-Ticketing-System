import os, re, sys

tests = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"
for f in sorted(os.listdir(tests)):
    if not (f.endswith(".test.jsx") or f.endswith(".test.js")):
        continue
    text = open(os.path.join(tests, f), encoding="utf-8").read()
    lines = text.splitlines()
    hits = []
    for n in ["badge", "Badge", "STATUS_TONE", "PRIORITY_TONE", "in_progress", "reopened", "priority", "status"]:
        for m in re.finditer(re.escape(n), text):
            ln = text[: m.start()].count("\n") + 1
            hits.append((ln, n))
    if hits:
        print("=====", f)
        seen = set()
        for ln, n in sorted(hits):
            if (ln, n) in seen:
                continue
            seen.add((ln, n))
            line = f"{ln}: {lines[ln - 1]}"
            line = line.encode("cp1252", "replace").decode("cp1252")
            print(line)

