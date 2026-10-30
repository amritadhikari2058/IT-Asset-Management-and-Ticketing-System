import re, sys

src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\pages.jsx", encoding="utf-8").read()
lines = src.splitlines()
out = []
for i, l in enumerate(lines):
    if re.match(r"^(export )?(function|const|class) ", l) or l.startswith("export default"):
        out.append(f"{i + 1}: {l}")
sys.stdout.write("\n".join(out) + "\n")

