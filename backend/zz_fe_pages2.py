import re, sys

src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\pages.jsx", encoding="utf-8").read()
lines = src.splitlines()
out = []
for i, l in enumerate(lines):
    if re.match(r"^(export )?(function|const|class) ", l) or l.startswith("export default"):
        out.append(f"{i + 1}: {l}")
        j = i + 1
        ctx = []
        while j < len(lines) and lines[j].strip() != "":
            ctx.append(f"{j + 1}: {lines[j]}")
            j += 1
        for c in ctx[:3]:
            out.append(c)
sys.stdout.write("\n".join(out) + "\n")

