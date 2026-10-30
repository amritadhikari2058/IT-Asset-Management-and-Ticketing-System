src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx", encoding="utf-8").read().splitlines()
for i, l in enumerate(src):
    if "STATUS_TONE" in l or "in_progress" in l or "reopened" in l or "PRIORITY_TONE" in l or "const text" in l or "Small status" in l:
        print(i, repr(l))
