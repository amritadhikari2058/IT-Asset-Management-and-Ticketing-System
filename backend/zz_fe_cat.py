src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx", encoding="utf-8").read().splitlines()
out = []
for i in range(228, 300):
    line = f"{i + 1}: {src[i]}"
    line = line.encode("cp1252", "replace").decode("cp1252")
    out.append(line)
import sys
sys.stdout.write("\n".join(out) + "\n")

