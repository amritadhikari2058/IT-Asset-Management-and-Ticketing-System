import os, re
base = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"
needles = ["Badge", "STATUS_TONE", "PRIORITY_TONE", "badge-", "Preview", "preview", "selected", "onToggle", "bulk", "Bulk", "prompt(", "report-filters", "input-date", "Categories", "category"]
for f in sorted(os.listdir(base)):
    if not (f.endswith(".jsx") or f.endswith(".js") or f.endswith(".css")):
        continue
    p = os.path.join(base, f)
    text = open(p, encoding="utf-8").read()
    hits = set()
    for n in needles:
        if n in text:
            hits.add(n)
    if hits:
        print(f, sorted(hits))

