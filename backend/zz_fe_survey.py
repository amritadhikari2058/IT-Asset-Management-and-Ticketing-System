import os
base = "D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src"
for f in sorted(os.listdir(base)):
    if f.endswith(".jsx") or f.endswith(".js") or f.endswith(".css"):
        p = os.path.join(base, f)
        n = len(open(p, encoding="utf-8").read().splitlines())
        print(f"{n}: {f}")

