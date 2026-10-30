import sys

src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\pages.jsx", encoding="utf-8").read().splitlines()
out = []
for i in range(1680, 1810):
    line = f"{i + 1}: {src[i]}"
    line = line.encode("cp1252", "replace").decode("cp1252")
    out.append(line)
sys.stdout.write("\n".join(out) + "\n")

