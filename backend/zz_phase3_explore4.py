src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\common\\views.py", encoding="utf-8").read().splitlines()
import sys
out = []
for i in range(0, len(src)):
    line = f"{i + 1}: {src[i]}"
    line = line.encode("cp1252", "replace").decode("cp1252")
    out.append(line)
sys.stdout.write("\n".join(out) + "\n")

