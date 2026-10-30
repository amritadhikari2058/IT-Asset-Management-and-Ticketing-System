p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\views.py"
lines = open(p, encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if "bulk" in l.lower() or ("def " in l and "action" in l):
        print(f"{i + 1}: {l}")

