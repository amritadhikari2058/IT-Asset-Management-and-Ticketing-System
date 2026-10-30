src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\index.css", encoding="utf-8").read().splitlines()
import sys
out = []
for i, l in enumerate(src):
    low = l.lower()
    if any(k in low for k in ["th-select", "select-cell", "toolbar", "badge-", "preview-media", "preview-", "input-date", "checkbox", "table.grid th", "grid td", "cell-actions", "photo", "thumbnail"]):
        line = f"{i + 1}: {l}"
        line = line.encode("cp1252", "replace").decode("cp1252")
        out.append(line)
sys.stdout.write("\n".join(out) + "\n")

