paths = [
    "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\assets\\tests.py",
    "D:\\IT-Asset-Management-and-Ticketing-System\\backend\\accounts\\tests.py",
]
for p in paths:
    lines = open(p, encoding="utf-8").read().splitlines()
    print("=====", p)
    for i, line in enumerate(lines):
        if "assigned_to" in line and ("Asset" in lines[i - 1] or "Asset" in line):
            for j in range(max(0, i - 6), min(len(lines), i + 7)):
                print(f"{j + 1}: {lines[j]}")
            print("-----")

