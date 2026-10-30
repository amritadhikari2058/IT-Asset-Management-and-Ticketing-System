src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx", encoding="utf-8").read()
lines = src.splitlines()
for i, l in enumerate(lines):
    if "th-select" in l or ("selectable" in l and "const" in l) or "muted small" in l:
        s = str(i) + ": " + l
        s = s.encode("cp1252", "replace").decode("cp1252")
        print(s)
