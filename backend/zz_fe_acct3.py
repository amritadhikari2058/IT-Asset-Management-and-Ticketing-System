src = open("D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\views.py", encoding="utf-8").read().splitlines()
import sys
sys.stdout.write(f"LEN {len(src)}\n")
for i in range(700, 760):
    if i < len(src):
        line = f"{i + 1}: {src[i]}"
        line = line.encode("cp1252", "replace").decode("cp1252")
        sys.stdout.write(line + "\n")

