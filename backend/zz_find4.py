p = "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\tests.py"
lines = open(p, encoding="utf-8").read().splitlines()
for i, line in enumerate(lines):
    if "assigned_to" in line:
        seg = lines[max(0, i - 8):i + 9]
        if any("Asset" in l for l in seg):
            print("---")
            for j in range(max(0, i - 8), min(len(lines), i + 9)):
                print(f"{j + 1}: {lines[j]}")
            print("-----")

