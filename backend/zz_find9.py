p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\tests.py"
lines = open(p, encoding="utf-8").read().splitlines()
out = []
for i, l in enumerate(lines):
    if "bulk_activate" in l or "bulk_deactivate" in l or "bulk_import" in l:
        for j in range(max(0, i - 2), min(len(lines), i + 40)):
            out.append(f"{j + 1}: {lines[j]}")
        out.append("-----")
print("\n".join(out))

