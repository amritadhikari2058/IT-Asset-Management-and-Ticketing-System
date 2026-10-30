src = open("D:\\IT-Asset-Management-and-Ticketing-System\\frontend\\src\\components.jsx", encoding="utf-8").read().splitlines()
for i, l in enumerate(src):
    if l.startswith("function ") or l.startswith("export function") or l.startswith("const ") or l.startswith("export const"):
        print(f"{i + 1}: {l}")

