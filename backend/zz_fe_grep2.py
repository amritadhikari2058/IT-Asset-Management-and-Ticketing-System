import os, re

base = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"
needles = ["badge badge", "In progress", "in progress", "Reopened", "reopened"]
for f in sorted(os.listdir(base)):
    if not (f.endswith(".jsx") or f.endswith(".js") or f.endswith(".css")):
        continue
    p = os.path.join(base, f)
    text = open(p, encoding="utf-8").read()
    hits = []
    for n in needles:
        for m in re.finditer(re.escape(n), text):
            ln = text[: m.start()].count("\n") + 1
            hits.append(f"{ln}:{n}")
    if hits:
        print("=====", f)
        for h in hits[:40]:
            print("   ", h)

